from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round


class SnOutIssue(models.Model):
    """委外发料单 / 退料单（来料加工）。

    发料：本厂原料仓 → 该代工厂委外库位（按 BOM × 数量 ×（1+损耗率上限），按批次先进先出分配）；
    退料：代工厂委外库位 → 本厂原料仓。都生成并完成库存调拨，批次全程可追。
    """
    _name = 'sn.out.issue'
    _description = '委外发料/退料单'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(string='单号', required=True, copy=False, readonly=True, default='/')
    kind = fields.Selection([('issue', '发料'), ('return', '退料')], string='类型', required=True, default='issue')
    order_id = fields.Many2one('sn.out.order', string='代工单', required=True, index=True, ondelete='cascade')
    factory_id = fields.Many2one(related='order_id.factory_id', store=True, string='代工厂')
    product_id = fields.Many2one(related='order_id.product_id', string='产品')
    date = fields.Datetime(string='日期', default=fields.Datetime.now, required=True)
    line_ids = fields.One2many('sn.out.issue.line', 'issue_id', string='物料明细')
    total_qty = fields.Float(string='合计数量', compute='_compute_total', store=True)
    picking_id = fields.Many2one('stock.picking', string='库存调拨', readonly=True, copy=False)
    handler = fields.Char(string='经办人')
    state = fields.Selection([('draft', '草稿'), ('done', '已完成'), ('cancel', '已取消')], string='状态',
                             default='draft', required=True, tracking=True)
    note = fields.Char(string='说明')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                code = 'sn.out.return' if vals.get('kind') == 'return' else 'sn.out.issue'
                vals['name'] = self.env['ir.sequence'].next_by_code(code) or '/'
        return super().create(vals_list)

    @api.depends('line_ids.qty')
    def _compute_total(self):
        for rec in self:
            rec.total_qty = sum(rec.line_ids.mapped('qty'))

    def _stock_location(self):
        wh = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        return wh.lot_stock_id

    def _fill_from_bom(self):
        """按 BOM 单耗 × 数量 ×（1+损耗率上限）− 已发净额，批次先进先出分配。"""
        Quant = self.env['stock.quant']
        for rec in self:
            order = rec.order_id
            done = order.issue_ids.filtered(lambda i: i.state == 'done')
            lines = [(5, 0, 0)]
            for product, (unit, std, need) in order._material_requirements().items():
                sent = sum(done.filtered(lambda i: i.kind == 'issue').line_ids.filtered(
                    lambda l: l.product_id == product).mapped('qty'))
                back = sum(done.filtered(lambda i: i.kind == 'return').line_ids.filtered(
                    lambda l: l.product_id == product).mapped('qty'))
                remain = float_round(need - (sent - back), precision_rounding=product.uom_id.rounding)
                if remain <= 0:
                    continue
                quants = Quant.search([('product_id', '=', product.id), ('location_id', 'child_of', rec._stock_location().id),
                                       ('quantity', '>', 0)], order='in_date, id')
                for q in quants:
                    if remain <= 0:
                        break
                    take = min(q.quantity - q.reserved_quantity, remain)
                    if take <= 0:
                        continue
                    lines.append((0, 0, {'product_id': product.id, 'lot_id': q.lot_id.id, 'qty': take,
                                         'std_qty': std, 'unit_qty': unit}))
                    remain -= take
                if remain > 0:
                    lines.append((0, 0, {'product_id': product.id, 'qty': remain, 'std_qty': std, 'unit_qty': unit}))
            rec.line_ids = lines
        return True

    def action_fill_from_bom(self):
        return self._fill_from_bom()

    def action_done(self, when=None):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('单据 %s 已处理。', rec.name))
            if not rec.line_ids:
                raise UserError(_('没有物料明细。'))
            order = rec.order_id
            if order.state not in ('released', 'producing', 'partial'):
                raise UserError(_('代工单 %s 当前状态不能发料/退料。', order.name))
            fac_loc = order.factory_id.location_id
            stock = rec._stock_location()
            src, dst = (stock, fac_loc) if rec.kind == 'issue' else (fac_loc, stock)
            for line in rec.line_ids:
                if line.product_id.tracking == 'lot' and not line.lot_id:
                    raise UserError(_('物料 %s 按批次管理，请指定批次。', line.product_id.display_name))
                avail = self.env['stock.quant']._get_available_quantity(line.product_id, src, lot_id=line.lot_id or None,
                                                                         strict=False)
                if float_compare(avail, line.qty, precision_rounding=line.product_id.uom_id.rounding) < 0:
                    raise UserError(_('%(loc)s 批次 %(lot)s 的 %(p)s 可用 %(a)s，不足 %(q)s。', loc=src.display_name,
                                      lot=line.lot_id.name or '-', p=line.product_id.display_name, a=avail, q=line.qty))
            ptype = self.env['stock.picking.type'].search(
                [('code', '=', 'internal'), ('warehouse_id.company_id', '=', self.env.company.id)], limit=1)
            picking = self.env['stock.picking'].create({
                'picking_type_id': ptype.id, 'location_id': src.id, 'location_dest_id': dst.id,
                'origin': '%s %s' % (rec.name, order.name), 'partner_id': order.factory_id.partner_id.id,
            })
            for line in rec.line_ids:
                move = self.env['stock.move'].create({
                    'product_id': line.product_id.id, 'product_uom_qty': line.qty,
                    'product_uom': line.product_id.uom_id.id, 'picking_id': picking.id,
                    'location_id': src.id, 'location_dest_id': dst.id,
                })
                line.move_id = move
            picking.action_confirm()
            for line in rec.line_ids:
                line.move_id.move_line_ids.unlink()
                self.env['stock.move.line'].create({
                    'move_id': line.move_id.id, 'picking_id': picking.id, 'product_id': line.product_id.id,
                    'product_uom_id': line.product_id.uom_id.id, 'lot_id': line.lot_id.id,
                    'quantity': line.qty, 'location_id': src.id, 'location_dest_id': dst.id,
                })
                line.move_id.picked = True
            picking.with_context(skip_backorder=True, picking_ids_not_to_backorder=picking.ids)._action_done()
            rec.write({'state': 'done', 'picking_id': picking.id, 'date': when or rec.date})
            order.message_post(body=_('%(k)s %(n)s 完成：%(d)s', k=dict(self._fields['kind'].selection)[rec.kind], n=rec.name,
                                      d='；'.join('%s 批次 %s %.1f%s' % (l.product_id.name, l.lot_id.name or '-', l.qty,
                                                                       l.product_id.uom_id.name) for l in rec.line_ids)))
            order.balance_ids._recompute_now()
        return True

    def action_cancel(self):
        self.filtered(lambda r: r.state == 'draft').write({'state': 'cancel'})
        return True


class SnOutIssueLine(models.Model):
    _name = 'sn.out.issue.line'
    _description = '委外发料/退料明细'
    _order = 'issue_id, id'

    issue_id = fields.Many2one('sn.out.issue', required=True, ondelete='cascade', index=True)
    kind = fields.Selection(related='issue_id.kind', store=True)
    state = fields.Selection(related='issue_id.state', store=True)
    order_id = fields.Many2one(related='issue_id.order_id', store=True)
    product_id = fields.Many2one('product.product', string='物料', required=True)
    uom_id = fields.Many2one(related='product_id.uom_id', string='单位')
    lot_id = fields.Many2one('stock.lot', string='批次', domain="[('product_id', '=', product_id)]")
    unit_qty = fields.Float(string='单耗(每件)', digits=(10, 6))
    std_qty = fields.Float(string='标准用量', digits=(12, 2))
    qty = fields.Float(string='数量', digits=(12, 2), required=True)
    move_id = fields.Many2one('stock.move', string='库存移动', readonly=True)
