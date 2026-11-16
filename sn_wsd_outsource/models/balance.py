from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_round


class SnOutBalance(models.Model):
    """委外物料平衡表（来料加工，按代工单 × 物料一行）。

    平衡式：发料 = 回货良品耗用 + 合理损耗 + 退料 + 超耗（代工厂结存须为 0）
      回货良品耗用 = 合格入库数 × BOM 单耗
      实际损耗     = 发料 − 退料 − 良品耗用 − 代工厂结存
      允许损耗     = 良品耗用 × 损耗率上限
      合理损耗     = min(实际损耗, 允许损耗)；超耗 = max(实际损耗 − 允许损耗, 0)
      超耗扣款     = 超耗 × 材料单价 × 扣款系数
    """
    _name = 'sn.out.balance'
    _description = '委外物料平衡'
    _inherit = ['mail.thread']
    _order = 'order_id desc, id'

    order_id = fields.Many2one('sn.out.order', string='代工单', required=True, index=True, ondelete='cascade')
    factory_id = fields.Many2one(related='order_id.factory_id', store=True, string='代工厂')
    finished_product_id = fields.Many2one(related='order_id.product_id', store=True, string='产品')
    product_id = fields.Many2one('product.product', string='物料', required=True)
    uom_id = fields.Many2one(related='product_id.uom_id', string='单位')
    lot_text = fields.Char(string='发料批次', readonly=True)
    unit_qty = fields.Float(string='单耗(kg/千件)', digits=(10, 3), readonly=True)
    loss_rate_max = fields.Float(related='order_id.loss_rate_max', string='损耗率上限(%)')
    issued_qty = fields.Float(string='发料', digits=(12, 2), readonly=True)
    good_qty = fields.Integer(string='良品数(件)', readonly=True)
    std_use_qty = fields.Float(string='良品耗用', digits=(12, 2), readonly=True)
    returned_qty = fields.Float(string='退料', digits=(12, 2), readonly=True)
    remaining_qty = fields.Float(string='代工厂结存', digits=(12, 2), tracking=True,
                                 help='代工厂盘点申报的未用原料，须退回后才能平衡')
    actual_loss_qty = fields.Float(string='实际损耗', digits=(12, 2), readonly=True)
    allowed_loss_qty = fields.Float(string='允许损耗', digits=(12, 2), readonly=True)
    reasonable_loss_qty = fields.Float(string='合理损耗', digits=(12, 2), readonly=True)
    excess_qty = fields.Float(string='超耗', digits=(12, 2), readonly=True)
    excess_rate = fields.Float(string='超耗率(%)', digits=(5, 2), readonly=True)
    actual_loss_rate = fields.Float(string='实际损耗率(%)', digits=(5, 2), readonly=True)
    price = fields.Float(string='材料单价(元)', digits=(10, 2))
    penalty_factor = fields.Float(related='order_id.penalty_factor', string='扣款系数')
    deduct_amount = fields.Float(string='超耗扣款(元)', digits=(12, 2), readonly=True)
    check_ok = fields.Boolean(string='平衡式成立', readonly=True)
    formula = fields.Char(string='平衡式', readonly=True)
    state = fields.Selection([('draft', '待确认'), ('confirmed', '已确认平衡')], string='状态', default='draft',
                             required=True, tracking=True)
    confirm_date = fields.Datetime(string='确认时间', readonly=True)
    consume_picking_id = fields.Many2one('stock.picking', string='核销调拨', readonly=True)

    @api.depends('order_id.name', 'product_id.name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s · %s' % (rec.order_id.name or '', rec.product_id.name or '')

    _order_product_unique = models.Constraint('unique(order_id, product_id)', '同一代工单同一物料只有一行平衡表。')

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        for rec in recs:
            if not rec.price:
                rec.price = rec.product_id.standard_price
        recs._refresh()
        return recs

    def write(self, vals):
        res = super().write(vals)
        if 'remaining_qty' in vals or 'price' in vals:
            self._refresh()
        return res

    def _refresh(self):
        for rec in self.filtered(lambda r: r.state == 'draft'):
            order = rec.order_id
            rnd = rec.product_id.uom_id.rounding
            lines = order.issue_ids.filtered(lambda i: i.state == 'done').line_ids.filtered(
                lambda l: l.product_id == rec.product_id)
            issued = sum(lines.filtered(lambda l: l.kind == 'issue').mapped('qty'))
            returned = sum(lines.filtered(lambda l: l.kind == 'return').mapped('qty'))
            req = order._material_requirements().get(rec.product_id)
            unit = req[0] if req else 0.0
            good = order.accepted_qty
            std = float_round(good * unit, precision_rounding=rnd)
            actual = float_round(issued - returned - std - rec.remaining_qty, precision_rounding=rnd)
            allowed = float_round(std * order.loss_rate_max / 100.0, precision_rounding=rnd)
            reasonable = max(min(actual, allowed), 0)
            excess = max(actual - allowed, 0)
            deduct = round(excess * (rec.price or 0) * (order.penalty_factor or 1.0), 2)
            ok = abs(issued - (std + reasonable + returned + excess + rec.remaining_qty)) < 0.01 and actual >= 0
            vals = {
                'lot_text': '、'.join(sorted(set(lines.filtered(lambda l: l.kind == 'issue').lot_id.mapped('name')))),
                'unit_qty': unit * 1000, 'issued_qty': issued, 'good_qty': good, 'std_use_qty': std,
                'returned_qty': returned, 'actual_loss_qty': actual, 'allowed_loss_qty': allowed,
                'reasonable_loss_qty': reasonable, 'excess_qty': excess,
                'excess_rate': round(excess * 100.0 / issued, 2) if issued else 0,
                'actual_loss_rate': round(actual * 100.0 / std, 2) if std else 0,
                'deduct_amount': deduct, 'check_ok': ok,
                'formula': '%.1f = %.1f + %.1f + %.1f + %.1f%s' % (
                    issued, std, reasonable, returned, excess,
                    (' + 结存 %.1f' % rec.remaining_qty) if rec.remaining_qty else ''),
            }
            super(SnOutBalance, rec).write(vals)
        return True

    def _recompute_now(self):
        return self._refresh()

    def action_refresh(self):
        return self._refresh()

    def action_confirm(self, when=None):
        """双方确认物料平衡：回货已全部检验处置、代工厂结存已退回、平衡式成立 → 核销委外库位物料。"""
        for rec in self:
            if rec.state != 'draft':
                continue
            order = rec.order_id
            rec._refresh()
            pend = order.receipt_ids.filtered(lambda r: r.state in ('draft', 'inspecting', 'inspected'))
            if pend:
                raise UserError(_('回货 %s 尚未检验入库，物料平衡不能确认。', '、'.join(pend.mapped('name'))))
            if rec.remaining_qty > 0:
                raise UserError(_('代工厂结存 %(q).2f %(u)s 未退回，请先办理退料，物料未平衡。',
                                  q=rec.remaining_qty, u=rec.uom_id.name))
            if not rec.check_ok:
                raise UserError(_('平衡式不成立（%s），请核对发料、退料与回货数据。', rec.formula))
            picking = rec._consume(when)
            super(SnOutBalance, rec).write({'state': 'confirmed', 'confirm_date': when or fields.Datetime.now(),
                                            'consume_picking_id': picking.id if picking else False})
            body = _('物料平衡确认：%(p)s %(f)s，超耗 %(e).2f %(u)s，扣款 %(d).2f 元。', p=rec.product_id.name,
                     f=rec.formula, e=rec.excess_qty, u=rec.uom_id.name, d=rec.deduct_amount)
            order.message_post(body=body)
        return True

    def _consume(self, when=None):
        """把留在代工厂委外库位的该物料（良品耗用 + 损耗 + 超耗）核销到生产耗用。"""
        self.ensure_one()
        order = self.order_id
        qty = self.issued_qty - self.returned_qty
        if qty <= 0:
            return False
        loc = order.factory_id.location_id
        dest = self.product_id.property_stock_production or self.env.ref('stock.stock_location_production',
                                                                         raise_if_not_found=False)
        quants = self.env['stock.quant'].search([('product_id', '=', self.product_id.id), ('location_id', '=', loc.id),
                                                 ('quantity', '>', 0)], order='in_date, id')
        ptype = self.env['stock.picking.type'].search(
            [('code', '=', 'internal'), ('warehouse_id.company_id', '=', self.env.company.id)], limit=1)
        picking = self.env['stock.picking'].create({
            'picking_type_id': ptype.id, 'location_id': loc.id, 'location_dest_id': dest.id,
            'origin': _('%s 委外耗用核销', order.name), 'partner_id': order.factory_id.partner_id.id})
        move = self.env['stock.move'].create({
            'product_id': self.product_id.id, 'product_uom_qty': qty, 'product_uom': self.product_id.uom_id.id,
            'picking_id': picking.id, 'location_id': loc.id, 'location_dest_id': dest.id})
        picking.action_confirm()
        move.move_line_ids.unlink()
        remain = qty
        # 只核销本单发出的批次
        lots = order.issue_ids.filtered(lambda i: i.state == 'done' and i.kind == 'issue').line_ids.filtered(
            lambda l: l.product_id == self.product_id).lot_id
        for q in quants.filtered(lambda q: not lots or q.lot_id in lots):
            if remain <= 0.0001:
                break
            take = min(q.quantity, remain)
            self.env['stock.move.line'].create({
                'move_id': move.id, 'picking_id': picking.id, 'product_id': self.product_id.id,
                'product_uom_id': self.product_id.uom_id.id, 'lot_id': q.lot_id.id, 'quantity': take,
                'location_id': loc.id, 'location_dest_id': dest.id})
            remain -= take
        if remain > 0.01:
            raise UserError(_('委外库位 %(l)s 的 %(p)s 账面不足（差 %(r).2f），请核对发料/退料。',
                              l=loc.display_name, p=self.product_id.display_name, r=remain))
        move.picked = True
        picking.with_context(cancel_backorder=True)._action_done()
        return picking
