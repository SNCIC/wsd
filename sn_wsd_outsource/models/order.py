from datetime import datetime, time, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .request import MODES

ORDER_STATES = [
    ('draft', '草稿'),
    ('released', '已下达'),
    ('producing', '生产中'),
    ('partial', '部分到货'),
    ('done', '已完成'),
    ('closed', '已关闭'),
    ('cancel', '已取消'),
]
RISK_LEVELS = [('normal', '正常'), ('watch', '关注'), ('high', '高风险'), ('overdue', '已逾期')]
RISK_RANK = {'normal': 0, 'watch': 1, 'high': 2, 'overdue': 3}


class SnOutOrder(models.Model):
    """代工单：整单代加工的核心单据。

    一张代工单 = 一个客户订单行（产品、数量、交期）交给一家代工厂；按外发模式驱动
    发料（来料加工）或模具外借（带模外发），回货检验入库，物料平衡后生成对账单结算。
    下达时生成采购单（加工费），回货入库走采购单收货，作为应付结算依据。
    """
    _name = 'sn.out.order'
    _description = '代工单'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='代工单号', required=True, copy=False, readonly=True, default='/')
    request_id = fields.Many2one('sn.out.request', string='外发申请', readonly=True, copy=False)
    quote_id = fields.Many2one('sn.out.quote', string='定点报价', readonly=True, copy=False)
    factory_id = fields.Many2one('sn.out.factory', string='代工厂', required=True, tracking=True, index=True)
    factory_partner_id = fields.Many2one(related='factory_id.partner_id', string='代工厂企业')
    sale_order_id = fields.Many2one('sale.order', string='客户订单', index=True)
    sale_line_id = fields.Many2one('sale.order.line', string='客户订单行')
    customer_id = fields.Many2one('res.partner', string='客户')
    plan_id = fields.Many2one('sn.inj.plan', string='来源注塑计划')
    product_id = fields.Many2one('product.product', string='产品', required=True, tracking=True)
    uom_id = fields.Many2one(related='product_id.uom_id', string='单位')
    qty = fields.Integer(string='代工数量', required=True, tracking=True)
    date_order = fields.Date(string='下达日期', copy=False)
    date_deadline = fields.Date(string='客户交期', required=True, tracking=True)
    date_promised = fields.Date(string='代工厂承诺交期', required=True, tracking=True)
    mode = fields.Selection(MODES, string='外发模式', required=True, default='turnkey', tracking=True)
    mold_id = fields.Many2one('sn.inj.mold', string='借出模具', tracking=True)
    bom_id = fields.Many2one('mrp.bom', string='用料 BOM', compute='_compute_bom', store=True, readonly=False)
    # 质量要求
    card_id = fields.Many2one('sn.inj.process.card', string='引用工艺卡',
                              domain="[('product_id', '=', product_id), ('state', '=', 'active')]")
    sample_no = fields.Char(string='封样编号')
    sample_date = fields.Date(string='封样日期')
    aql = fields.Selection([('0.65', 'AQL 0.65'), ('1.0', 'AQL 1.0'), ('2.5', 'AQL 2.5')],
                           string='检验 AQL', default='0.65')
    quality_req = fields.Text(string='质量要求')
    # 价格
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    unit_price = fields.Float(string='加工单价(元/件)', digits=(10, 4), tracking=True)
    amount_planned = fields.Monetary(string='合同金额', compute='_compute_amount', store=True)
    qty_tolerance = fields.Float(string='交付容差(%)', default=0.5, digits=(4, 2),
                                 help='合格入库数量 ≥ 代工数量 ×（1 − 容差）即可按完成结案')
    loss_rate_max = fields.Float(string='损耗率上限(%)', digits=(5, 2), default=2.0, tracking=True)
    penalty_factor = fields.Float(string='超耗扣款系数', default=1.0, digits=(4, 2),
                                  help='超耗扣款 = 超耗量 × 材料单价 × 系数')
    purchase_id = fields.Many2one('purchase.order', string='采购单', readonly=True, copy=False)
    # 子单据
    issue_ids = fields.One2many('sn.out.issue', 'order_id', string='发料/退料')
    loan_ids = fields.One2many('sn.out.mold.loan', 'order_id', string='模具外借')
    progress_ids = fields.One2many('sn.out.progress', 'order_id', string='进度回报')
    receipt_ids = fields.One2many('sn.out.receipt', 'order_id', string='回货')
    iqc_ids = fields.One2many('sn.out.iqc', 'order_id', string='回货检验')
    balance_ids = fields.One2many('sn.out.balance', 'order_id', string='物料平衡表')
    statement_line_ids = fields.One2many('sn.out.statement.line', 'order_id', string='对账明细')
    statement_id = fields.Many2one('sn.out.statement', string='对账单', compute='_compute_statement', store=True)
    # 进度与数量
    produced_qty = fields.Integer(string='代工厂已产', compute='_compute_qty', store=True)
    last_report = fields.Datetime(string='最近回报', compute='_compute_qty', store=True)
    delivered_qty = fields.Integer(string='已送货', compute='_compute_qty', store=True)
    pending_qty = fields.Integer(string='待检/待入库', compute='_compute_qty', store=True)
    accepted_qty = fields.Integer(string='合格入库', compute='_compute_qty', store=True)
    rejected_qty = fields.Integer(string='判退', compute='_compute_qty', store=True)
    achieve_rate = fields.Float(string='达成率(%)', compute='_compute_qty', store=True, digits=(5, 1))
    produce_rate = fields.Float(string='生产进度(%)', compute='_compute_qty', store=True, digits=(5, 1))
    loan_state = fields.Selection([('none', '无'), ('loaned', '外借中'), ('returned', '已归还')],
                                  string='模具', compute='_compute_loan_state', store=True)
    # 风险
    risk_level = fields.Selection(RISK_LEVELS, string='交期风险', default='normal', readonly=True, copy=False,
                                  tracking=True)
    risk_text = fields.Char(string='风险说明', readonly=True, copy=False)
    # 平衡与结算
    balance_state = fields.Selection([('na', '不适用'), ('open', '未平衡'), ('balanced', '已平衡')],
                                     string='物料平衡', compute='_compute_balance_state', store=True)
    deduct_amount = fields.Monetary(string='超耗扣款', compute='_compute_balance_state', store=True)
    close_reason = fields.Char(string='关闭原因', tracking=True)
    date_done = fields.Date(string='结案日期', copy=False)
    user_id = fields.Many2one('res.users', string='委外跟单', default=lambda self: self.env.user, tracking=True)
    state = fields.Selection(ORDER_STATES, string='状态', default='draft', required=True, tracking=True, copy=False,
                             index=True)
    note = fields.Text(string='备注')

    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.out.order') or '/'
        recs = super().create(vals_list)
        for rec in recs:
            if not rec.card_id:
                rec.card_id = self.env['sn.inj.process.card'].search(
                    [('product_id', '=', rec.product_id.id), ('state', '=', 'active')], limit=1)
        return recs

    @api.depends('product_id', 'mode')
    def _compute_bom(self):
        for rec in self:
            if rec.mode == 'consign' and rec.product_id and not rec.bom_id:
                rec.bom_id = self.env['mrp.bom']._bom_find(rec.product_id)[rec.product_id]
            elif rec.mode != 'consign':
                rec.bom_id = False

    @api.depends('qty', 'unit_price')
    def _compute_amount(self):
        for rec in self:
            rec.amount_planned = rec.qty * rec.unit_price

    @api.depends('progress_ids.produced_qty', 'progress_ids.date', 'receipt_ids.qty', 'receipt_ids.state',
                 'receipt_ids.accepted_qty', 'receipt_ids.rejected_qty', 'qty')
    def _compute_qty(self):
        for rec in self:
            prog = rec.progress_ids.sorted('date')[-1:] if rec.progress_ids else rec.progress_ids
            receipts = rec.receipt_ids.filtered(lambda r: r.state != 'cancel')
            rec.produced_qty = prog.produced_qty if prog else 0
            rec.last_report = prog.date if prog else False
            rec.delivered_qty = sum(receipts.mapped('qty'))
            rec.pending_qty = sum(receipts.filtered(lambda r: r.state in ('draft', 'inspecting', 'inspected')).mapped('qty'))
            rec.accepted_qty = sum(receipts.filtered(lambda r: r.state == 'done').mapped('accepted_qty'))
            rec.rejected_qty = sum(receipts.filtered(lambda r: r.state in ('done', 'returned')).mapped('rejected_qty'))
            rec.achieve_rate = round(rec.accepted_qty * 100.0 / rec.qty, 1) if rec.qty else 0
            rec.produce_rate = round(min(max(rec.produced_qty, rec.accepted_qty + rec.pending_qty) * 100.0 / rec.qty, 100), 1) \
                if rec.qty else 0

    @api.depends('loan_ids.state')
    def _compute_loan_state(self):
        for rec in self:
            loans = rec.loan_ids.filtered(lambda l: l.state != 'cancel')
            if not loans:
                rec.loan_state = 'none'
            elif loans.filtered(lambda l: l.state in ('draft', 'loaned')):
                rec.loan_state = 'loaned'
            else:
                rec.loan_state = 'returned'

    @api.depends('mode', 'balance_ids.state', 'balance_ids.deduct_amount', 'issue_ids.state')
    def _compute_balance_state(self):
        for rec in self:
            issued = rec.issue_ids.filtered(lambda i: i.state == 'done' and i.kind == 'issue')
            if not issued:
                rec.balance_state = 'na'      # 包工包料/带模外发无我方发料；来料加工尚未发料
            elif rec.balance_ids and all(b.state == 'confirmed' for b in rec.balance_ids):
                rec.balance_state = 'balanced'
            else:
                rec.balance_state = 'open'
            rec.deduct_amount = sum(rec.balance_ids.mapped('deduct_amount'))

    @api.depends('statement_line_ids.statement_id')
    def _compute_statement(self):
        for rec in self:
            rec.statement_id = rec.statement_line_ids.statement_id[:1]

    @api.constrains('mode', 'mold_id', 'loss_rate_max', 'qty')
    def _check_mode(self):
        for rec in self:
            if rec.qty <= 0:
                raise ValidationError(_('代工数量必须大于 0。'))
            if rec.mode == 'mold_loan' and not rec.mold_id:
                raise ValidationError(_('带模外发必须指定借出的模具。'))
            if rec.mold_id and rec.product_id not in rec.mold_id.product_ids:
                raise ValidationError(_('模具 %(m)s 不生产产品 %(p)s。', m=rec.mold_id.sn, p=rec.product_id.display_name))
            if rec.loss_rate_max < 0 or rec.loss_rate_max > 20:
                raise ValidationError(_('损耗率上限应在 0–20% 之间。'))

    # ------------------------------------------------------------------
    # 下达：生成采购单（加工费）
    # ------------------------------------------------------------------
    def _prepare_purchase(self):
        self.ensure_one()
        mode_label = dict(MODES)[self.mode]
        return {
            'partner_id': self.factory_id.partner_id.id,
            'origin': '%s %s' % (self.name, self.sale_order_id.name or ''),
            'partner_ref': self.name,
            'date_planned': datetime.combine(self.date_promised, time(8, 0)),
            'order_line': [(0, 0, {
                'product_id': self.product_id.id,
                'name': _('%(p)s 整单代加工（%(m)s，代工单 %(o)s）', p=self.product_id.display_name, m=mode_label, o=self.name),
                'product_qty': self.qty,
                'price_unit': self.unit_price,
                'date_planned': datetime.combine(self.date_promised, time(8, 0)),
            })],
        }

    def action_release(self, when=None):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('只有草稿代工单可以下达。'))
            rec.factory_id._check_awardable()
            if rec.unit_price <= 0:
                raise UserError(_('请先填写加工单价。'))
            if rec.mode == 'consign' and not rec.bom_id:
                raise UserError(_('来料加工需要产品 %s 的用料 BOM（按 BOM + 损耗计算发料）。', rec.product_id.display_name))
            if rec.mode == 'mold_loan':
                rec.mold_id._check_loanable()
            po = self.env['purchase.order'].create(rec._prepare_purchase())
            po.button_confirm()
            rec.write({'state': 'released', 'purchase_id': po.id,
                       'date_order': (when and fields.Date.to_date(when)) or fields.Date.context_today(rec)})
            if rec.plan_id and rec.plan_id.state in ('draft', 'confirmed'):
                rec.plan_id.action_cancel()
                rec.plan_id.message_post(body=_('本计划已整单转外发：代工单 %(o)s（%(f)s）。', o=rec.name, f=rec.factory_id.name))
            rec.message_post(body=_('代工单下达，生成采购单 %(po)s（%(q)s 件 × %(p)s 元）。',
                                    po=po.name, q=rec.qty, p=rec.unit_price))
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state not in ('draft', 'released'):
                raise UserError(_('已开始生产的代工单不能取消，请走关闭。'))
            if rec.issue_ids.filtered(lambda i: i.state == 'done') or rec.loan_ids.filtered(lambda l: l.state == 'loaned'):
                raise UserError(_('已发料或模具已借出，不能取消。'))
            if rec.purchase_id and rec.purchase_id.state != 'cancel':
                rec.purchase_id.button_cancel()
            rec.state = 'cancel'
        return True

    # ------------------------------------------------------------------
    # 发料 / 模具
    # ------------------------------------------------------------------
    def _material_requirements(self):
        """BOM 单耗 × 数量 ×（1 + 损耗率上限）。返回 {product: (单耗, 标准用量, 含损耗应发)}"""
        self.ensure_one()
        res = {}
        if not self.bom_id:
            return res
        factor = self.qty / (self.bom_id.product_qty or 1.0)
        for line in self.bom_id.bom_line_ids:
            unit = line.product_qty / (self.bom_id.product_qty or 1.0)
            std = line.product_qty * factor
            res[line.product_id] = (unit, std, std * (1 + self.loss_rate_max / 100.0))
        return res

    def action_create_issue(self):
        self.ensure_one()
        if self.mode != 'consign':
            raise UserError(_('只有来料加工模式需要我方发料。'))
        if self.state not in ('released', 'producing', 'partial'):
            raise UserError(_('代工单下达后才能发料。'))
        issue = self.env['sn.out.issue'].create({'order_id': self.id, 'kind': 'issue'})
        issue._fill_from_bom()
        return {'type': 'ir.actions.act_window', 'res_model': 'sn.out.issue', 'res_id': issue.id, 'view_mode': 'form'}

    def action_create_return(self):
        self.ensure_one()
        issue = self.env['sn.out.issue'].create({'order_id': self.id, 'kind': 'return'})
        return {'type': 'ir.actions.act_window', 'res_model': 'sn.out.issue', 'res_id': issue.id, 'view_mode': 'form'}

    def action_loan_mold(self, when=None, expect=None):
        self.ensure_one()
        if self.mode != 'mold_loan':
            raise UserError(_('只有带模外发需要借出模具。'))
        if self.state not in ('released', 'producing', 'partial'):
            raise UserError(_('代工单下达后才能借出模具。'))
        loan = self.env['sn.out.mold.loan'].create({
            'order_id': self.id, 'mold_id': self.mold_id.id, 'factory_id': self.factory_id.id,
            'date_expect_back': expect or self.date_promised + timedelta(days=3)})
        loan.action_loan(when=when)
        return loan

    # ------------------------------------------------------------------
    # 进度 / 回货
    # ------------------------------------------------------------------
    def report_progress(self, produced_qty, shots=0, stage='mass', note=False, source='manual', when=None, good_qty=0):
        self.ensure_one()
        if self.state not in ('released', 'producing', 'partial'):
            raise UserError(_('代工单 %(o)s 状态为「%(s)s」，不接受进度回报。', o=self.name,
                              s=dict(ORDER_STATES)[self.state]))
        prog = self.env['sn.out.progress'].create({
            'order_id': self.id, 'produced_qty': produced_qty, 'shots': shots, 'stage': stage,
            'note': note, 'source': source, 'good_qty': good_qty,
            'date': when or fields.Datetime.now()})
        return prog

    def _after_progress(self):
        for rec in self:
            if rec.state == 'released' and rec.produced_qty > 0:
                rec.state = 'producing'
        self._update_risk()

    def action_new_receipt(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'sn.out.receipt', 'view_mode': 'form',
                'context': {'default_order_id': self.id, 'default_qty': max(self.qty - self.delivered_qty, 0)}}

    def _after_receipt(self):
        for rec in self:
            if rec.state in ('released', 'producing') and rec.delivered_qty > 0:
                rec.state = 'partial'
        self._update_risk()

    # ------------------------------------------------------------------
    # 交期风险
    # ------------------------------------------------------------------
    def _update_risk(self, today=None):
        today = today or fields.Date.context_today(self)
        for rec in self:
            level, text = 'normal', False
            if rec.state in ('released', 'producing', 'partial'):
                deadline = rec.date_promised or rec.date_deadline
                ok_qty = rec.accepted_qty + rec.pending_qty
                remain = rec.qty - ok_qty
                made = max(rec.produced_qty, ok_qty)
                to_make = max(rec.qty - made, 0)
                if remain > 0 and today > deadline:
                    level, text = 'overdue', _('已超承诺交期 %(d)s 天，未交 %(r)s 件', d=(today - deadline).days, r=remain)
                elif remain > 0:
                    days_left = (deadline - today).days + 1
                    cap = rec.factory_id.capacity_pcs_day or 0
                    cap_label = _('代工厂可承接产能')
                    if rec.mold_id and rec.mold_id.std_cycle:
                        # 带模外发：受我方模具节拍约束（有效穴数 × 24h × 85% ÷ 标准周期）
                        mold_cap = int(rec.mold_id._cavity_for(rec.product_id) * 86400 * 0.85 / rec.mold_id.std_cycle)
                        if not cap or mold_cap < cap:
                            cap, cap_label = mold_cap, _('模具理论产能')
                    need = to_make / days_left if days_left > 0 else to_make
                    start = rec.date_order or today
                    span = max((deadline - start).days, 1)
                    time_pct = min(max((today - start).days / span, 0), 1)
                    made_pct = made / rec.qty if rec.qty else 1
                    if cap and need > cap:
                        level, text = 'high', _('剩余 %(d)s 天需日产 %(n).0f 件，超出%(lb)s %(c)s 件/日',
                                                 d=days_left, n=need, lb=cap_label, c=cap)
                    elif made_pct + 0.15 < time_pct:
                        level, text = 'watch', _('进度落后：时间已过 %(t).0f%%，完成 %(m).0f%%', t=time_pct * 100, m=made_pct * 100)
                    elif rec.state in ('producing', 'partial') and rec.last_report and \
                            fields.Datetime.now() - rec.last_report > timedelta(hours=48):
                        level, text = 'watch', _('超过 48 小时无进度回报')
                    elif days_left <= 2 and to_make > 0:
                        level, text = 'watch', _('距交期 %(d)s 天，尚余 %(n)s 件未产出', d=days_left, n=to_make)
            if RISK_RANK[level] > RISK_RANK[rec.risk_level or 'normal'] and level in ('high', 'overdue'):
                rec.message_post(body=_('交期预警「%(l)s」：%(t)s', l=dict(RISK_LEVELS)[level], t=text))
                rec.activity_schedule('mail.mail_activity_data_todo', user_id=rec.user_id.id or self.env.uid,
                                      summary=_('代工交期%s', dict(RISK_LEVELS)[level]), note=text)
            rec.write({'risk_level': level, 'risk_text': text})
        return True

    @api.model
    def _cron_update_risk(self):
        self.search([('state', 'in', ('released', 'producing', 'partial'))])._update_risk()

    # ------------------------------------------------------------------
    # 物料平衡 / 结算 / 结案
    # ------------------------------------------------------------------
    def action_compute_balance(self):
        """生成/刷新物料平衡表（来料加工按发出的每种物料一行）。"""
        Balance = self.env['sn.out.balance']
        for rec in self:
            products = rec.issue_ids.filtered(lambda i: i.state == 'done').line_ids.product_id
            if not products and rec.mode == 'consign':
                products = self.env['product.product'].browse([p.id for p in rec._material_requirements()])
            for product in products:
                if not rec.balance_ids.filtered(lambda b: b.product_id == product):
                    Balance.create({'order_id': rec.id, 'product_id': product.id})
        return True

    def _check_settle_ready(self, closing=False):
        """结算/关单前置：回货全部检验处置完毕、物料已平衡、模具已归还。"""
        for rec in self:
            pend = rec.receipt_ids.filtered(lambda r: r.state in ('draft', 'inspecting', 'inspected'))
            if pend:
                raise UserError(_('代工单 %(o)s 还有回货 %(r)s 未检验/未入库，不能结算。',
                                  o=rec.name, r='、'.join(pend.mapped('name'))))
            if rec.balance_state == 'open':
                raise UserError(_('代工单 %s 物料未平衡（发料 ≠ 良品耗用 + 合理损耗 + 退料 + 超耗，或代工厂仍有结存未退），'
                                  '不能结算关单。请先完成退料并确认物料平衡表。', rec.name))
            if rec.loan_ids.filtered(lambda l: l.state == 'loaned'):
                raise UserError(_('代工单 %s 借出的模具尚未归还，不能结算关单。', rec.name))
            if not closing and rec.accepted_qty <= 0:
                raise UserError(_('代工单 %s 尚无合格入库数量，无可结算金额。', rec.name))
        return True

    def action_create_statement(self):
        self._check_settle_ready()
        statement = self.env['sn.out.statement'].create_for_orders(self)
        return {'type': 'ir.actions.act_window', 'res_model': 'sn.out.statement', 'res_id': statement.id,
                'view_mode': 'form'}

    def _finish(self, state, when=None, reason=None):
        for rec in self:
            if rec.state not in ('released', 'producing', 'partial'):
                raise UserError(_('代工单 %s 当前状态不能结案。', rec.name))
            rec._check_settle_ready(closing=(state == 'closed'))
            if rec.accepted_qty > 0 and not (rec.statement_id and rec.statement_id.state in ('confirmed', 'done')):
                raise UserError(_('代工单 %s 的对账单尚未双方确认，不能结案。', rec.name))
            vals = {'state': state, 'date_done': when or fields.Date.context_today(rec),
                    'risk_level': 'normal', 'risk_text': False}
            if reason:
                vals['close_reason'] = reason
            rec.write(vals)
            if rec.purchase_id and state == 'closed':
                # 短交关闭：采购单剩余数量不再收货
                for line in rec.purchase_id.order_line:
                    if line.qty_received < line.product_qty:
                        line.product_qty = max(line.qty_received, 0)
            rec.activity_unlink(['mail.mail_activity_data_todo'])
        return True

    def action_done(self, when=None):
        for rec in self:
            if rec.accepted_qty < rec.qty * (1 - (rec.qty_tolerance or 0) / 100.0):
                raise UserError(_('合格入库 %(a)s 件少于代工数量 %(q)s 件（容差 %(t)s%%），如不再交货请使用「关闭」。',
                                  a=rec.accepted_qty, q=rec.qty, t=rec.qty_tolerance))
        return self._finish('done', when=when)

    def action_close(self, reason=None, when=None):
        reason = reason or self.env.context.get('close_reason')
        for rec in self:
            if not (reason or rec.close_reason):
                raise UserError(_('请填写关闭原因。'))
        return self._finish('closed', when=when, reason=reason)

    # ------------------------------------------------------------------
    def action_view_purchase(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'purchase.order', 'res_id': self.purchase_id.id,
                'view_mode': 'form'}
