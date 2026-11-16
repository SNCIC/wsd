from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SnOutStatement(models.Model):
    """代工对账单：加工费 = 合格入库数 × 单价；扣款 = 超耗扣款 + 让步接收扣款；应付 = 加工费 − 扣款。"""
    _name = 'sn.out.statement'
    _description = '代工对账单'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string='对账单号', required=True, copy=False, readonly=True, default='/')
    factory_id = fields.Many2one('sn.out.factory', string='代工厂', required=True, index=True)
    partner_id = fields.Many2one(related='factory_id.partner_id', string='代工厂企业')
    date = fields.Date(string='对账日期', default=fields.Date.context_today, required=True)
    period = fields.Char(string='对账期间')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    line_ids = fields.One2many('sn.out.statement.line', 'statement_id', string='对账明细')
    order_ids = fields.Many2many('sn.out.order', string='关联代工单', compute='_compute_orders')
    order_text = fields.Char(string='代工单', compute='_compute_orders')
    good_qty = fields.Integer(string='结算良品数', compute='_compute_amount', store=True)
    amount_goods = fields.Monetary(string='加工费', compute='_compute_amount', store=True)
    amount_excess = fields.Monetary(string='超耗扣款', compute='_compute_amount', store=True)
    amount_concession = fields.Monetary(string='让步扣款', compute='_compute_amount', store=True)
    amount_deduct = fields.Monetary(string='扣款合计', compute='_compute_amount', store=True)
    amount_total = fields.Monetary(string='应付金额', compute='_compute_amount', store=True)
    confirm_user = fields.Char(string='代工厂确认人')
    confirm_date = fields.Datetime(string='确认时间', readonly=True)
    state = fields.Selection([('draft', '草稿'), ('confirmed', '双方已确认'), ('done', '已结算')],
                             string='状态', default='draft', required=True, tracking=True)
    note = fields.Text(string='备注')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.out.statement') or '/'
        return super().create(vals_list)

    @api.depends('line_ids.order_id')
    def _compute_orders(self):
        for rec in self:
            rec.order_ids = rec.line_ids.order_id
            rec.order_text = '、'.join(rec.line_ids.order_id.mapped('name'))

    @api.depends('line_ids.amount', 'line_ids.kind', 'line_ids.qty')
    def _compute_amount(self):
        for rec in self:
            goods = rec.line_ids.filtered(lambda l: l.kind == 'goods')
            rec.good_qty = int(sum(goods.mapped('qty')))
            rec.amount_goods = sum(goods.mapped('amount'))
            rec.amount_excess = -sum(rec.line_ids.filtered(lambda l: l.kind == 'excess').mapped('amount'))
            rec.amount_concession = -sum(rec.line_ids.filtered(lambda l: l.kind == 'concession').mapped('amount'))
            rec.amount_deduct = rec.amount_excess + rec.amount_concession
            rec.amount_total = rec.amount_goods - rec.amount_deduct

    @api.model
    def create_for_orders(self, orders, date=None):
        """按代工单生成对账单（同一代工厂可多单合并）。前置：物料已平衡、回货已全部处置。"""
        if len(orders.factory_id) != 1:
            raise UserError(_('一张对账单只能对应一家代工厂。'))
        orders._check_settle_ready()
        done = orders.filtered(lambda o: o.statement_id)
        if done:
            raise UserError(_('代工单 %s 已生成对账单。', '、'.join(done.mapped('name'))))
        lines = []
        for order in orders:
            for rcp in order.receipt_ids.filtered(lambda r: r.state == 'done').sorted('date'):
                lines.append((0, 0, {
                    'order_id': order.id, 'receipt_id': rcp.id, 'kind': 'goods',
                    'name': _('%(r)s 合格入库（批号 %(l)s）', r=rcp.name, l=rcp.lot_name),
                    'qty': rcp.accepted_qty, 'price': order.unit_price,
                    'amount': round(rcp.accepted_qty * order.unit_price, 2)}))
                if rcp.disposition == 'concession' and rcp.iqc_id.concession_pct:
                    amt = round(rcp.accepted_qty * order.unit_price * rcp.iqc_id.concession_pct / 100.0, 2)
                    lines.append((0, 0, {
                        'order_id': order.id, 'receipt_id': rcp.id, 'kind': 'concession', 'sequence': 20,
                        'name': _('%(r)s 让步接收扣款 %(p)s%%（%(d)s）', r=rcp.name, p=rcp.iqc_id.concession_pct,
                                  d=rcp.iqc_id.defect_text or '-'),
                        'qty': rcp.accepted_qty, 'price': -order.unit_price * rcp.iqc_id.concession_pct / 100.0,
                        'amount': -amt}))
            for bal in order.balance_ids.filtered(lambda b: b.deduct_amount > 0):
                lines.append((0, 0, {
                    'order_id': order.id, 'kind': 'excess', 'sequence': 30,
                    'name': _('%(p)s 超耗 %(q).2f %(u)s（超耗率 %(r).2f%%）× %(pr)s 元 × 系数 %(f)s',
                              p=bal.product_id.name, q=bal.excess_qty, u=bal.uom_id.name, r=bal.excess_rate,
                              pr=bal.price, f=bal.penalty_factor),
                    'qty': bal.excess_qty, 'price': -bal.price * bal.penalty_factor, 'amount': -bal.deduct_amount}))
        dates = orders.receipt_ids.filtered(lambda r: r.state == 'done').mapped('date')
        period = '%s 至 %s' % (min(dates).strftime('%Y-%m-%d'), max(dates).strftime('%Y-%m-%d')) if dates else False
        st = self.create({'factory_id': orders.factory_id.id, 'line_ids': lines, 'period': period,
                          'date': date or fields.Date.context_today(self)})
        for order in orders:
            order.message_post(body=_('生成对账单 %(s)s：应付 %(a).2f 元。', s=st.name, a=st.amount_total))
        return st

    def action_confirm(self, confirm_user=None, when=None):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('对账单 %s 已确认。', rec.name))
            rec.write({'state': 'confirmed', 'confirm_date': when or fields.Datetime.now(),
                       'confirm_user': confirm_user or rec.confirm_user or rec.factory_id.contact})
        return True

    def action_done(self):
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_('对账单须双方确认后才能结算。'))
            rec.state = 'done'
        return True

    def action_reset(self):
        for rec in self:
            if rec.line_ids.order_id.filtered(lambda o: o.state in ('done', 'closed')):
                raise UserError(_('代工单已结案，对账单不能退回。'))
            rec.state = 'draft'
        return True


class SnOutStatementLine(models.Model):
    _name = 'sn.out.statement.line'
    _description = '代工对账明细'
    _order = 'statement_id, order_id, sequence, id'

    statement_id = fields.Many2one('sn.out.statement', required=True, ondelete='cascade', index=True)
    order_id = fields.Many2one('sn.out.order', string='代工单', index=True)
    receipt_id = fields.Many2one('sn.out.receipt', string='回货单')
    sequence = fields.Integer(default=10)
    kind = fields.Selection([('goods', '加工费'), ('concession', '让步扣款'), ('excess', '超耗扣款')],
                            string='类别', required=True)
    name = fields.Char(string='摘要', required=True)
    product_id = fields.Many2one(related='order_id.product_id', string='产品')
    qty = fields.Float(string='数量', digits=(12, 2))
    price = fields.Float(string='单价(元)', digits=(10, 4))
    currency_id = fields.Many2one(related='statement_id.currency_id')
    amount = fields.Monetary(string='金额(元)')
