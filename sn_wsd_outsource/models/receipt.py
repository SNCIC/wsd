from odoo import _, api, fields, models
from odoo.exceptions import UserError

# GB/T 2828.1 一般检验水平 II：批量 → 样本量字码
LOT_CODES = [(8, 'A'), (15, 'B'), (25, 'C'), (50, 'D'), (90, 'E'), (150, 'F'), (280, 'G'), (500, 'H'),
             (1200, 'J'), (3200, 'K'), (10000, 'L'), (35000, 'M'), (150000, 'N'), (500000, 'P')]
CODE_N = {'A': 2, 'B': 3, 'C': 5, 'D': 8, 'E': 13, 'F': 20, 'G': 32, 'H': 50, 'J': 80, 'K': 125, 'L': 200,
          'M': 315, 'N': 500, 'P': 800}
# 正常检验一次抽样（箭头已按标准落到对应方案）：字码 → (样本量, Ac, Re)
AQL_PLAN = {
    '0.65': {'A': (20, 0, 1), 'B': (20, 0, 1), 'C': (20, 0, 1), 'D': (20, 0, 1), 'E': (20, 0, 1), 'F': (20, 0, 1),
             'G': (20, 0, 1), 'H': (20, 0, 1), 'J': (80, 1, 2), 'K': (125, 2, 3), 'L': (200, 3, 4),
             'M': (315, 5, 6), 'N': (500, 7, 8), 'P': (800, 10, 11)},
    '1.0': {'A': (13, 0, 1), 'B': (13, 0, 1), 'C': (13, 0, 1), 'D': (13, 0, 1), 'E': (13, 0, 1), 'F': (13, 0, 1),
            'G': (13, 0, 1), 'H': (50, 1, 2), 'J': (80, 2, 3), 'K': (125, 3, 4), 'L': (200, 5, 6),
            'M': (315, 7, 8), 'N': (500, 10, 11), 'P': (800, 14, 15)},
    '2.5': {'A': (5, 0, 1), 'B': (5, 0, 1), 'C': (5, 0, 1), 'D': (8, 0, 1), 'E': (13, 1, 2), 'F': (20, 1, 2),
            'G': (32, 2, 3), 'H': (50, 3, 4), 'J': (80, 5, 6), 'K': (125, 7, 8), 'L': (200, 10, 11),
            'M': (315, 14, 15), 'N': (500, 21, 22), 'P': (800, 21, 22)},
}
DEFAULT_ITEMS = [
    ('外观', '对照封样：无缺料、飞边、缩水、银纹、黑点、顶白'),
    ('关键尺寸', '按图纸/检验规范关键尺寸全检样本'),
    ('单件重量', '对照工艺卡单件重 ±1.5%'),
    ('装配验证', '与配合件试装无干涉、卡扣到位'),
    ('包装标识', '每箱标签含代工单号、批号、数量'),
]


def sample_plan(lot_qty, aql='0.65'):
    code = 'P'
    for upper, c in LOT_CODES:
        if lot_qty <= upper:
            code = c
            break
    n, ac, re_ = AQL_PLAN.get(aql or '0.65', AQL_PLAN['0.65'])[code]
    return code, min(n, lot_qty), ac, re_


class SnOutReceipt(models.Model):
    """代工回货：登记送货 → 自动生成回货检验 → 判定 → 合格/让步/挑选入库，判退退回。"""
    _name = 'sn.out.receipt'
    _description = '代工回货'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(string='回货单号', required=True, copy=False, readonly=True, default='/')
    order_id = fields.Many2one('sn.out.order', string='代工单', required=True, index=True, ondelete='cascade')
    factory_id = fields.Many2one(related='order_id.factory_id', store=True, string='代工厂')
    product_id = fields.Many2one(related='order_id.product_id', store=True, string='产品')
    mode = fields.Selection(related='order_id.mode', string='外发模式')
    date = fields.Datetime(string='到货时间', default=fields.Datetime.now, required=True)
    date_promised = fields.Date(related='order_id.date_promised', string='承诺交期')
    on_time = fields.Boolean(string='按期', compute='_compute_on_time', store=True)
    qty = fields.Integer(string='送货数量', required=True)
    box_qty = fields.Integer(string='箱数')
    delivery_no = fields.Char(string='送货单号')
    factory_lot = fields.Char(string='代工厂批号')
    lot_name = fields.Char(string='入库批号', readonly=True, copy=False)
    iqc_id = fields.Many2one('sn.out.iqc', string='回货检验', readonly=True, copy=False)
    iqc_result = fields.Selection(related='iqc_id.result', string='检验结果', store=True)
    disposition = fields.Selection(related='iqc_id.disposition', string='处置', store=True)
    accepted_qty = fields.Integer(string='入库数量', readonly=True, copy=False)
    rejected_qty = fields.Integer(string='不良/退回', readonly=True, copy=False)
    picking_id = fields.Many2one('stock.picking', string='入库单', readonly=True, copy=False)
    state = fields.Selection([('draft', '已登记'), ('inspecting', '待检验'), ('inspected', '已检待入库'),
                              ('done', '已入库'), ('returned', '已退回'), ('cancel', '已取消')],
                             string='状态', default='draft', required=True, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.out.receipt') or '/'
        return super().create(vals_list)

    @api.depends('date', 'order_id.date_promised')
    def _compute_on_time(self):
        for rec in self:
            rec.on_time = bool(rec.date and rec.order_id.date_promised
                               and fields.Datetime.context_timestamp(rec, rec.date).date() <= rec.order_id.date_promised)

    def action_confirm(self):
        """登记到货：自动生成回货检验（GB/T 2828.1 抽样）。"""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('回货 %s 已送检。', rec.name))
            order = rec.order_id
            if order.state not in ('released', 'producing', 'partial'):
                raise UserError(_('代工单 %s 当前状态不能收货。', order.name))
            if rec.qty <= 0:
                raise UserError(_('送货数量必须大于 0。'))
            over = order.delivered_qty - order.qty
            if over > order.qty * 0.03:
                raise UserError(_('累计送货超出代工数量 3%% 以上，请核对。'))
            seq = len(order.receipt_ids.filtered(lambda r: r.lot_name)) + 1
            rec.lot_name = '%s-%02d' % (order.name, seq)
            rec.iqc_id = self.env['sn.out.iqc'].create({'receipt_id': rec.id, 'date': rec.date})
            rec.state = 'inspecting'
            order._after_receipt()
        return True

    def _after_iqc(self):
        for rec in self:
            rec.write({'state': 'inspected', 'accepted_qty': rec.iqc_id.accepted_qty,
                       'rejected_qty': rec.qty - rec.iqc_id.accepted_qty})

    def action_stock_in(self, when=None):
        """入库：拦截未检验；合格/让步/挑选后按入库数量完成采购收货（批次 = 入库批号）。"""
        for rec in self:
            if rec.state in ('draft', 'inspecting') or not rec.iqc_id or rec.iqc_id.state != 'done':
                raise UserError(_('回货 %s 尚未完成检验判定，不能入库。', rec.name))
            if rec.state != 'inspected':
                raise UserError(_('回货 %s 当前状态不能入库。', rec.name))
            if rec.iqc_id.disposition == 'return':
                raise UserError(_('回货 %s 判退返工，请执行「退回代工厂」。', rec.name))
            qty = rec.accepted_qty
            if qty <= 0:
                raise UserError(_('可入库数量为 0。'))
            picking = rec._receive_purchase(qty)
            rec.write({'state': 'done', 'picking_id': picking.id})
            if when:
                picking.date_done = when
            rec.order_id.balance_ids._refresh()
            rec.order_id._after_receipt()
            rec.order_id.message_post(body=_('回货 %(r)s 入库 %(q)s 件（批号 %(l)s）。', r=rec.name, q=qty, l=rec.lot_name))
        return True

    def _receive_purchase(self, qty):
        self.ensure_one()
        po = self.order_id.purchase_id
        picking = po.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))[:1]
        if not picking:
            raise UserError(_('采购单 %s 没有待收货的入库单（可能已收满）。', po.name))
        move = picking.move_ids.filtered(lambda m: m.product_id == self.order_id.product_id)[:1]
        if qty > move.product_uom_qty:
            raise UserError(_('入库数量 %(q)s 超出采购单待收 %(r)s。', q=qty, r=move.product_uom_qty))
        move.move_line_ids.unlink()
        vals = {'move_id': move.id, 'picking_id': picking.id, 'product_id': move.product_id.id,
                'product_uom_id': move.product_uom.id, 'quantity': qty,
                'location_id': move.location_id.id, 'location_dest_id': move.location_dest_id.id}
        if move.product_id.tracking == 'lot':
            vals['lot_name'] = self.lot_name
        self.env['stock.move.line'].create(vals)
        move.picked = True
        picking.origin = '%s / %s' % (po.name, self.name)
        picking.with_context(skip_backorder=True, cancel_backorder=False,
                             )._action_done()
        return picking

    def action_return_goods(self):
        """判退：整批退回代工厂返工（不入库）。"""
        for rec in self:
            if rec.state != 'inspected' or rec.iqc_id.disposition != 'return':
                raise UserError(_('只有判退返工的回货可以退回。'))
            rec.write({'state': 'returned', 'accepted_qty': 0, 'rejected_qty': rec.qty})
            rec.order_id.message_post(body=_('回货 %(r)s 判退 %(q)s 件，已退回 %(f)s 返工。原因：%(d)s',
                                             r=rec.name, q=rec.qty, f=rec.factory_id.name, d=rec.iqc_id.defect_text or '-'))
            rec.order_id._update_risk()
        return True

    def action_cancel(self):
        self.filtered(lambda r: r.state == 'draft').write({'state': 'cancel'})
        return True


class SnOutIqc(models.Model):
    """回货检验（轻量来料检验）：GB/T 2828.1 抽样、检验项目、缺陷（复用注塑缺陷代码）、判定与处置。"""
    _name = 'sn.out.iqc'
    _description = '代工回货检验'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(string='检验单号', required=True, copy=False, readonly=True, default='/')
    receipt_id = fields.Many2one('sn.out.receipt', string='回货单', required=True, ondelete='cascade', index=True)
    order_id = fields.Many2one(related='receipt_id.order_id', store=True, string='代工单')
    factory_id = fields.Many2one(related='receipt_id.factory_id', store=True, string='代工厂')
    product_id = fields.Many2one(related='receipt_id.product_id', store=True, string='产品')
    card_id = fields.Many2one(related='order_id.card_id', string='引用工艺卡')
    sample_no = fields.Char(related='order_id.sample_no', string='封样编号')
    date = fields.Datetime(string='检验时间', default=fields.Datetime.now)
    lot_qty = fields.Integer(string='批量', compute='_compute_plan', store=True)
    aql = fields.Selection(related='order_id.aql', string='AQL')
    sample_code = fields.Char(string='样本字码', compute='_compute_plan', store=True)
    sample_qty = fields.Integer(string='样本量', compute='_compute_plan', store=True)
    ac = fields.Integer(string='Ac', compute='_compute_plan', store=True)
    re_qty = fields.Integer(string='Re', compute='_compute_plan', store=True)
    item_ids = fields.One2many('sn.out.iqc.item', 'iqc_id', string='检验项目')
    defect_ids = fields.One2many('sn.out.iqc.defect', 'iqc_id', string='不良明细')
    acre_text = fields.Char(string='接收/拒收数', compute='_compute_plan', store=True)
    defect_qty = fields.Integer(string='样本不良数', compute='_compute_defect', store=True)
    defect_text = fields.Char(string='不良原因', compute='_compute_defect', store=True)
    result = fields.Selection([('pass', '合格'), ('fail', '不合格')], string='判定', readonly=True, copy=False)
    disposition = fields.Selection([('accept', '合格入库'), ('concession', '让步接收'), ('sort', '挑选使用'),
                                    ('return', '判退返工')], string='处置', copy=False)
    sort_bad_qty = fields.Integer(string='挑选剔除数')
    concession_pct = fields.Float(string='让步扣款比例(%)', digits=(5, 1))
    accepted_qty = fields.Integer(string='可入库数', compute='_compute_accepted', store=True)
    inspector = fields.Char(string='检验员')
    state = fields.Selection([('draft', '待检验'), ('done', '已判定')], string='状态', default='draft',
                             required=True, tracking=True)
    note = fields.Text(string='检验结论')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.out.iqc') or '/'
        recs = super().create(vals_list)
        for rec in recs.filtered(lambda r: not r.item_ids):
            items = list(DEFAULT_ITEMS)
            card = rec.order_id.card_id
            if card and card.part_weight:
                items[2] = ('单件重量', _('工艺卡 %(c)s 单件重 %(w)s g ±1.5%%', c=card.name, w=card.part_weight))
            if rec.order_id.sample_no:
                items[0] = ('外观', _('对照封样 %s：无缺料、飞边、缩水、银纹、黑点、顶白', rec.order_id.sample_no))
            rec.item_ids = [(0, 0, {'sequence': i, 'name': n, 'standard': s}) for i, (n, s) in enumerate(items)]
        return recs

    @api.depends('receipt_id.qty', 'order_id.aql')
    def _compute_plan(self):
        for rec in self:
            lot = rec.receipt_id.qty or 0
            code, n, ac, re_ = sample_plan(lot, rec.order_id.aql) if lot else ('', 0, 0, 1)
            rec.lot_qty, rec.sample_code, rec.sample_qty, rec.ac, rec.re_qty = lot, code, n, ac, re_
            rec.acre_text = 'Ac %s / Re %s' % (ac, re_) if lot else False

    @api.depends('defect_ids.qty', 'defect_ids.defect_id')
    def _compute_defect(self):
        for rec in self:
            rec.defect_qty = sum(rec.defect_ids.mapped('qty'))
            rec.defect_text = '、'.join('%s×%s' % (d.defect_id.name, d.qty) for d in rec.defect_ids if d.qty)

    @api.depends('result', 'disposition', 'lot_qty', 'defect_qty', 'sort_bad_qty', 'state')
    def _compute_accepted(self):
        for rec in self:
            if rec.state != 'done':
                rec.accepted_qty = 0
            elif rec.disposition == 'return':
                rec.accepted_qty = 0
            elif rec.disposition == 'sort':
                rec.accepted_qty = max(rec.lot_qty - rec.sort_bad_qty, 0)
            else:
                rec.accepted_qty = max(rec.lot_qty - rec.defect_qty, 0)

    def action_judge(self, disposition=None, inspector=None, when=None):
        """判定：样本不良数 ≤ Ac 合格，≥ Re 不合格（不合格须选择处置：判退返工 / 让步接收 / 挑选使用）。"""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('检验单 %s 已判定。', rec.name))
            if rec.item_ids.filtered(lambda i: not i.result):
                raise UserError(_('还有检验项目未录入结果。'))
            result = 'pass' if rec.defect_qty <= rec.ac and not rec.item_ids.filtered(lambda i: i.result == 'ng') else 'fail'
            disp = disposition or rec.disposition
            if result == 'pass':
                disp = 'accept'
            elif not disp or disp == 'accept':
                raise UserError(_('样本不良 %(d)s 件 ≥ Re=%(r)s，判定不合格，请选择处置方式（判退返工/让步接收/挑选使用）。',
                                  d=rec.defect_qty, r=rec.re_qty))
            if disp == 'sort' and not rec.sort_bad_qty:
                raise UserError(_('挑选使用请填写挑选剔除数。'))
            vals = {'result': result, 'disposition': disp, 'state': 'done'}
            if inspector:
                vals['inspector'] = inspector
            if when:
                vals['date'] = when
            rec.write(vals)
            rec.receipt_id._after_iqc()
            rec.order_id.message_post(body=_('回货检验 %(n)s：样本 %(s)s 件，不良 %(d)s 件（%(t)s），判定「%(r)s」，处置「%(p)s」。',
                                             n=rec.name, s=rec.sample_qty, d=rec.defect_qty, t=rec.defect_text or '无',
                                             r=dict(self._fields['result'].selection)[result],
                                             p=dict(self._fields['disposition'].selection)[disp]))
        return True

    def action_pass_all_items(self):
        self.item_ids.filtered(lambda i: not i.result).write({'result': 'ok'})
        return True


class SnOutIqcItem(models.Model):
    _name = 'sn.out.iqc.item'
    _description = '回货检验项目'
    _order = 'iqc_id, sequence, id'

    iqc_id = fields.Many2one('sn.out.iqc', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string='检验项目', required=True)
    standard = fields.Char(string='标准/依据')
    measured = fields.Char(string='实测')
    result = fields.Selection([('ok', '合格'), ('ng', '不合格')], string='结果')


class SnOutIqcDefect(models.Model):
    _name = 'sn.out.iqc.defect'
    _description = '回货检验不良明细'
    _order = 'iqc_id, qty desc, id'

    iqc_id = fields.Many2one('sn.out.iqc', required=True, ondelete='cascade', index=True)
    factory_id = fields.Many2one(related='iqc_id.factory_id', store=True, string='代工厂')
    product_id = fields.Many2one(related='iqc_id.product_id', store=True, string='产品')
    defect_id = fields.Many2one('sn.inj.defect', string='缺陷', required=True)
    severity = fields.Selection([('major', '主要'), ('minor', '次要'), ('critical', '致命')], string='等级',
                                default='major')
    qty = fields.Integer(string='数量', required=True, default=1)
    note = fields.Char(string='说明')
