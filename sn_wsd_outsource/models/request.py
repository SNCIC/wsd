import math
from datetime import datetime, time, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

REASON_TYPES = [
    ('load', '机台满负荷'),
    ('tonnage', '吨位/机型不足'),
    ('urgent', '交期紧急'),
    ('process', '工艺不具备'),
    ('mold', '模具产能不足'),
]
MODES = [('turnkey', '包工包料'), ('consign', '来料加工'), ('mold_loan', '带模外发')]
# 机台计划可用率：两班 24h × 85%（扣除换模、保养、计划停机）
MACHINE_HOURS_PER_DAY = 24 * 0.85


class SnOutRequest(models.Model):
    """外发申请与询价比价：从客户销售订单或注塑排产计划发起整单外发。"""
    _name = 'sn.out.request'
    _description = '外发申请与询价'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='申请单号', required=True, copy=False, readonly=True, default='/')
    source = fields.Selection([('sale', '客户销售订单'), ('plan', '注塑排产计划'), ('manual', '手工')],
                              string='发起来源', default='sale', required=True)
    sale_order_id = fields.Many2one('sale.order', string='客户订单', index=True)
    sale_line_id = fields.Many2one('sale.order.line', string='订单行')
    plan_id = fields.Many2one('sn.inj.plan', string='注塑计划')
    customer_id = fields.Many2one('res.partner', string='客户')
    product_id = fields.Many2one('product.product', string='产品', required=True, tracking=True)
    qty = fields.Integer(string='外发数量', required=True, tracking=True)
    date_need = fields.Date(string='要求交期', required=True, tracking=True)
    mold_id = fields.Many2one('sn.inj.mold', string='本厂模具',
                              help='带模外发时借出的模具；也用于测算本厂所需机时')
    suggest_mode = fields.Selection(MODES, string='建议外发模式')
    reason_type = fields.Selection(REASON_TYPES, string='外发原因', required=True, default='load', tracking=True)
    reason = fields.Text(string='原因说明')
    need_hours = fields.Float(string='本单需机时(h)', readonly=True)
    load_line_ids = fields.One2many('sn.out.request.load', 'request_id', string='本厂机台负荷')
    load_summary = fields.Char(string='负荷结论', readonly=True)
    load_pct = fields.Float(string='可用机台负荷(%)', readonly=True)
    quote_ids = fields.One2many('sn.out.quote', 'request_id', string='询价比价')
    quote_count = fields.Integer(compute='_compute_quote_count')
    awarded_quote_id = fields.Many2one('sn.out.quote', string='定点报价', readonly=True, copy=False)
    order_id = fields.Many2one('sn.out.order', string='代工单', readonly=True, copy=False)
    user_id = fields.Many2one('res.users', string='申请人', default=lambda self: self.env.user)
    date_request = fields.Date(string='申请日期', default=fields.Date.context_today)
    state = fields.Selection([('draft', '草稿'), ('quoting', '询价中'), ('awarded', '已定点'), ('cancel', '已取消')],
                             string='状态', default='draft', required=True, tracking=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.out.request') or '/'
        return super().create(vals_list)

    @api.depends('quote_ids')
    def _compute_quote_count(self):
        for rec in self:
            rec.quote_count = len(rec.quote_ids)

    # ------------------------------------------------------------------
    # 本厂负荷评估
    # ------------------------------------------------------------------
    def _candidate_molds(self):
        self.ensure_one()
        return self.mold_id or self.env['sn.inj.mold'].search(
            [('product_ids', 'in', self.product_id.ids), ('mold_state', 'not in', ('scrapped', 'sealed'))])

    def action_eval_load(self):
        """按交期窗口测算可做该产品的机台（吨位匹配模具适用范围）已排机时与剩余能力。"""
        Plan = self.env['sn.inj.plan']
        for rec in self:
            molds = rec._candidate_molds()
            if not molds:
                raise UserError(_('产品 %s 没有可用模具，无法评估本厂负荷。', rec.product_id.display_name))
            best = max(molds, key=lambda m: m._cavity_for(rec.product_id) or 0)
            cavity = best._cavity_for(rec.product_id) or 1
            rec.need_hours = round(math.ceil(rec.qty / cavity) * (best.std_cycle or 30) / 3600.0, 1)
            start = self.env.context.get('out_eval_now') or fields.Datetime.now()
            end = datetime.combine(rec.date_need, time(23, 59)) - timedelta(hours=8)
            days = max((end - start).total_seconds() / 86400.0, 0.5)
            avail = days * MACHINE_HOURS_PER_DAY
            machines = self.env['sn.inj.machine'].search([])
            machines = machines.filtered(lambda mc: any(
                (not m.tonnage_min or mc.tonnage >= m.tonnage_min) and (not m.tonnage_max or mc.tonnage <= m.tonnage_max)
                for m in molds))
            lines = [(5, 0, 0)]
            tot_plan = tot_avail = 0.0
            for mc in machines:
                planned = 0.0
                seen = set()
                for plan in Plan.search([('machine_id', '=', mc.id), ('state', 'in', ('draft', 'confirmed', 'running')),
                                         ('date_start', '<', end), ('id', '!=', rec.plan_id.id)]):
                    key = (plan.mold_id.id, plan.date_start)
                    if key in seen:          # 家族模一模多品联产：同模同时段只占一次机时
                        continue
                    seen.add(key)
                    remain = plan.planned_hours * max(1 - (plan.progress or 0) / 100.0, 0)
                    p_start = max(plan.date_start, start)
                    p_end = max(plan.date_end or p_start, p_start)
                    span = (p_end - p_start).total_seconds() / 3600.0
                    if span <= 0:
                        continue
                    inside = (min(p_end, end) - p_start).total_seconds() / 3600.0
                    planned += remain * max(min(inside / span, 1), 0)
                if mc.run_state == 'fault':
                    planned += min(avail * 0.3, 24)    # 故障停机预计损失
                load = planned / avail * 100 if avail else 0
                lines.append((0, 0, {
                    'machine_id': mc.id, 'tonnage': mc.tonnage, 'avail_hours': round(avail, 1),
                    'planned_hours': round(planned, 1), 'free_hours': round(max(avail - planned, 0), 1),
                    'load_pct': round(load, 1)}))
                tot_plan += planned
                tot_avail += avail
            free = max(tot_avail - tot_plan, 0)
            rec.load_line_ids = lines
            rec.load_pct = round(tot_plan / tot_avail * 100, 1) if tot_avail else 0
            if not machines:
                rec.load_summary = _('本厂无吨位匹配的机台（模具适用 %s–%sT），需外发。',
                                     min(molds.mapped('tonnage_min')), max(molds.mapped('tonnage_max')))
            else:
                rec.load_summary = _('可做机台 %(n)s 台，交期前可用 %(a).0f h、已排 %(p).0f h（负荷 %(l).0f%%）；'
                                     '本单需 %(need).0f h，%(con)s',
                                     n=len(machines), a=tot_avail, p=tot_plan, l=rec.load_pct, need=rec.need_hours,
                                     con=_('缺口 %.0f h，建议外发', rec.need_hours - free) if rec.need_hours > free
                                     else _('剩余能力可覆盖'))
        return True

    # ------------------------------------------------------------------
    def action_start_quote(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('只有草稿状态可以发起询价。'))
            if not rec.load_line_ids and not self.env.context.get('out_skip_load'):
                rec.action_eval_load()
            rec.state = 'quoting'
        return True

    def action_invite(self, factories):
        """向多家代工厂发起询价（生成待报价行）。"""
        self.ensure_one()
        exist = self.quote_ids.factory_id
        for fac in factories - exist:
            self.env['sn.out.quote'].create({'request_id': self.id, 'factory_id': fac.id})
        if self.state == 'draft':
            self.action_start_quote()
        return True

    def action_cancel(self):
        self.filtered(lambda r: r.state in ('draft', 'quoting')).write({'state': 'cancel'})
        return True

    def action_view_order(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'sn.out.order', 'res_id': self.order_id.id,
                'view_mode': 'form'}


class SnOutRequestLoad(models.Model):
    _name = 'sn.out.request.load'
    _description = '外发申请-本厂机台负荷'
    _order = 'request_id, load_pct desc'

    request_id = fields.Many2one('sn.out.request', required=True, ondelete='cascade', index=True)
    machine_id = fields.Many2one('sn.inj.machine', string='机台')
    tonnage = fields.Integer(string='吨位(T)')
    avail_hours = fields.Float(string='可用机时(h)')
    planned_hours = fields.Float(string='已排机时(h)')
    free_hours = fields.Float(string='剩余机时(h)')
    load_pct = fields.Float(string='负荷(%)')
    load_level = fields.Selection([('ok', '可插单'), ('busy', '紧张'), ('full', '满负荷')], string='判定',
                                  compute='_compute_level')

    @api.depends('load_pct')
    def _compute_level(self):
        for rec in self:
            rec.load_level = 'full' if rec.load_pct >= 95 else ('busy' if rec.load_pct >= 80 else 'ok')


class SnOutQuote(models.Model):
    """询价比价行：单价、交期、评级综合打分（价格 40 + 交期 30 + 评级 30）。"""
    _name = 'sn.out.quote'
    _description = '代工询价报价'
    _order = 'request_id, score desc, id'

    request_id = fields.Many2one('sn.out.request', string='外发申请', required=True, ondelete='cascade', index=True)
    factory_id = fields.Many2one('sn.out.factory', string='代工厂', required=True)
    coop_state = fields.Selection(related='factory_id.coop_state', string='合作状态')
    rating = fields.Selection(related='factory_id.rating', string='评级')
    rating_score = fields.Float(related='factory_id.rating_score', string='绩效得分')
    capacity_pcs_day = fields.Integer(related='factory_id.capacity_pcs_day', string='日产能(件)')
    mode = fields.Selection(MODES, string='报价模式')
    unit_price = fields.Float(string='加工单价(元/件)', digits=(10, 4))
    lead_days = fields.Integer(string='交货周期(天)')
    date_promise = fields.Date(string='承诺交期')
    loss_rate = fields.Float(string='承诺损耗率(%)', digits=(5, 2))
    amount = fields.Float(string='报价金额(元)', compute='_compute_amount', store=True)
    late_days = fields.Integer(string='晚于要求(天)', compute='_compute_score', store=True)
    score = fields.Float(string='综合得分', compute='_compute_score', store=True, digits=(5, 1))
    is_best = fields.Boolean(string='推荐', compute='_compute_score', store=True)
    awarded = fields.Boolean(string='已定点', readonly=True, copy=False)
    state = fields.Selection([('wait', '待报价'), ('quoted', '已报价'), ('awarded', '已定点'), ('lost', '未中选')],
                             string='报价状态', default='wait', required=True)
    note = fields.Char(string='报价说明')

    @api.depends('unit_price', 'request_id.qty')
    def _compute_amount(self):
        for rec in self:
            rec.amount = round(rec.unit_price * rec.request_id.qty, 2)

    @api.depends('unit_price', 'date_promise', 'factory_id.rating_score', 'factory_id.coop_state',
                 'request_id.date_need', 'request_id.quote_ids.unit_price', 'state')
    def _compute_score(self):
        for req in self.mapped('request_id'):
            quotes = req.quote_ids.filtered(lambda q: q.unit_price > 0)
            low = min(quotes.mapped('unit_price')) if quotes else 0
            best = False
            for q in req.quote_ids:
                q.late_days = max((q.date_promise - req.date_need).days, 0) if q.date_promise and req.date_need else 0
                if not q.unit_price:
                    q.score = 0
                    continue
                price = 40.0 * low / q.unit_price if low else 0
                delivery = max(30.0 - q.late_days * 6, 0)
                rating = 0.3 * (q.factory_id.rating_score or 70)
                q.score = round(price + delivery + rating, 1)
            ok = req.quote_ids.filtered(lambda q: q.unit_price > 0 and q.factory_id.coop_state != 'suspended')
            if ok:
                best = max(ok, key=lambda q: q.score)
            for q in req.quote_ids:
                q.is_best = q == best

    def write(self, vals):
        res = super().write(vals)
        if 'unit_price' in vals:
            for rec in self.filtered(lambda q: q.state == 'wait' and q.unit_price > 0):
                rec.state = 'quoted'
        return res

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        recs.filtered(lambda q: q.unit_price > 0).write({'state': 'quoted'})
        return recs

    def action_award(self):
        """定点：校验代工厂合作状态，生成代工单（草稿）。"""
        self.ensure_one()
        req = self.request_id
        if req.state != 'quoting':
            raise UserError(_('外发申请 %s 不在询价中，不能定点。', req.name))
        self.factory_id._check_awardable()
        if self.unit_price <= 0:
            raise UserError(_('代工厂「%s」尚未报价，不能定点。', self.factory_id.name))
        mode = self.mode or req.suggest_mode or 'turnkey'
        order = self.env['sn.out.order'].create({
            'request_id': req.id, 'quote_id': self.id, 'factory_id': self.factory_id.id,
            'sale_order_id': req.sale_order_id.id, 'sale_line_id': req.sale_line_id.id,
            'plan_id': req.plan_id.id, 'customer_id': req.customer_id.id,
            'product_id': req.product_id.id, 'qty': req.qty, 'date_deadline': req.date_need,
            'date_promised': self.date_promise or req.date_need, 'mode': mode,
            'mold_id': req.mold_id.id if mode == 'mold_loan' else False,
            'unit_price': self.unit_price, 'loss_rate_max': self.loss_rate or 2.0,
        })
        (req.quote_ids - self).filtered(lambda q: q.state in ('wait', 'quoted')).write({'state': 'lost'})
        self.write({'awarded': True, 'state': 'awarded'})
        req.write({'state': 'awarded', 'awarded_quote_id': self.id, 'order_id': order.id})
        req.message_post(body=_('定点代工厂「%(f)s」，单价 %(p)s 元/件，承诺交期 %(d)s，生成代工单 %(o)s。',
                                f=self.factory_id.name, p=self.unit_price, d=self.date_promise or '-', o=order.name))
        return {'type': 'ir.actions.act_window', 'res_model': 'sn.out.order', 'res_id': order.id, 'view_mode': 'form'}
