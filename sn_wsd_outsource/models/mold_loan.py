from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.sn_wsd_injection.models.mold import MOLD_STATES  # noqa: F401  (保持状态口径一致)


class SnOutMoldLoan(models.Model):
    """模具外借（带模外发）。

    借出：模具须在库、保养未逾期、寿命未到期 → 工装「领用」，库位转到代工厂委外库位，
    模具状态显示「外借-代工厂」，履历写入工装记录；
    归还：登记代工厂生产模次 → 累加模具累计/周期模次（寿命、保养进度随之更新），工装「归还」，
    库位回原模具库位；达到保养阈值自动生成保养任务。
    """
    _name = 'sn.out.mold.loan'
    _description = '模具外借记录'
    _inherit = ['mail.thread']
    _order = 'date_out desc, id desc'

    name = fields.Char(string='外借单号', required=True, copy=False, readonly=True, default='/')
    order_id = fields.Many2one('sn.out.order', string='代工单', index=True, ondelete='restrict')
    mold_id = fields.Many2one('sn.inj.mold', string='模具', required=True, index=True, tracking=True)
    mold_name = fields.Char(related='mold_id.name', string='模具名称')
    cavity_text = fields.Char(related='mold_id.cavity_text', string='穴数')
    factory_id = fields.Many2one('sn.out.factory', string='借往代工厂', required=True, index=True, tracking=True)
    date_out = fields.Datetime(string='借出时间', readonly=True)
    date_expect_back = fields.Date(string='约定归还日期')
    date_back = fields.Datetime(string='实际归还时间', readonly=True)
    origin_location_id = fields.Many2one('stock.location', string='原存放库位', readonly=True)
    shots_out = fields.Integer(string='借出时累计模次', readonly=True)
    shots_at_factory = fields.Integer(string='代工厂生产模次')
    shots_back = fields.Integer(string='归还后累计模次', readonly=True)
    life_progress_back = fields.Float(string='归还后寿命进度(%)', readonly=True)
    days_out = fields.Integer(string='外借天数', compute='_compute_days')
    overdue = fields.Boolean(string='超期未还', compute='_compute_days')
    condition_out = fields.Char(string='借出状态确认', default='外观、水路、顶出、热流道检查正常，随模附件齐全')
    condition_back = fields.Char(string='归还验收')
    state = fields.Selection([('draft', '草稿'), ('loaned', '外借中'), ('returned', '已归还'), ('cancel', '已取消')],
                             string='状态', default='draft', required=True, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.out.mold.loan') or '/'
        return super().create(vals_list)

    @api.depends('date_out', 'date_back', 'date_expect_back', 'state')
    def _compute_days(self):
        now = fields.Datetime.now()
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.date_out:
                rec.days_out = ((rec.date_back or now) - rec.date_out).days
            else:
                rec.days_out = 0
            rec.overdue = bool(rec.state == 'loaned' and rec.date_expect_back and today > rec.date_expect_back)

    def _set_record_info(self, action, reason, when, qty=False):
        """把外借信息写到工装履历最新一条记录上（沿用工装履历）。"""
        rec = self.env['sn.tooling.record'].search(
            [('tooling_id', '=', self.mold_id.tooling_id.id), ('action', '=', action)], order='id desc', limit=1)
        vals = {'reason': reason}
        if when:
            vals['occurred_at'] = when
        if rec:
            rec.sudo().write(vals)
        return rec

    def action_loan(self, when=None):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('外借单 %s 已处理。', rec.name))
            mold = rec.mold_id
            mold._check_loanable()
            tooling = mold.tooling_id.sudo()
            when = when or fields.Datetime.now()
            tooling.action_issue()
            label = _('外借至 %(f)s（代工单 %(o)s）', f=rec.factory_id.name, o=rec.order_id.name or '-')
            rec._set_record_info('issue', label, when)
            rec.write({'state': 'loaned', 'date_out': when, 'origin_location_id': tooling.location_id.id,
                       'shots_out': tooling.total_usage_count})
            tooling.location_id = rec.factory_id.location_id
            mold.loan_id = rec
            mold.message_post(body=_('模具%(l)s，借出时累计模次 %(s)s，约定 %(d)s 归还。',
                                     l=label, s=tooling.total_usage_count, d=rec.date_expect_back or '-'))
        return True

    def action_return(self, shots=None, when=None, condition=None):
        for rec in self:
            if rec.state != 'loaned':
                raise UserError(_('只有外借中的模具可以归还。'))
            shots = rec.shots_at_factory if shots is None else shots
            if not shots or shots < 0:
                raise UserError(_('请登记代工厂生产模次（模具计数器读数差）。'))
            mold = rec.mold_id
            tooling = mold.tooling_id.sudo()
            when = when or fields.Datetime.now()
            limit = tooling.template_id.scrap_count_limit
            tooling.write({'total_usage_count': tooling.total_usage_count + shots,
                           'cycle_usage_count': tooling.cycle_usage_count + shots})
            tooling._record('usage', qty=shots)
            rec._set_record_info('usage', _('代工厂 %(f)s 生产模次（代工单 %(o)s）', f=rec.factory_id.name,
                                            o=rec.order_id.name or '-'), when)
            if tooling.state == 'issued':
                tooling.action_return()
                rec._set_record_info('return', _('自 %s 归还入库', rec.factory_id.name), when)
            tooling.location_id = rec.origin_location_id
            mold.loan_id = False
            rec.write({'state': 'returned', 'date_back': when, 'shots_at_factory': shots,
                       'shots_back': tooling.total_usage_count, 'life_progress_back': mold.life_progress,
                       'condition_back': condition or rec.condition_back or _('归还验收正常')})
            msg = _('模具自 %(f)s 归还，代工厂生产 %(s)s 模次，累计 %(t)s 模次（寿命进度 %(p).1f%%）。',
                    f=rec.factory_id.name, s=shots, t=tooling.total_usage_count, p=mold.life_progress)
            if limit and tooling.total_usage_count >= limit:
                msg += _(' 已达设计寿命，请走报废/翻新评审。')
            threshold = mold.maint_cycle - (mold.maint_remind or int(mold.maint_cycle * 0.1)) if mold.maint_cycle else 0
            Maint = self.env['sn.inj.mold.maint']
            if threshold and mold.cycle_usage_count >= threshold and not Maint.search_count(
                    [('mold_id', '=', mold.id), ('state', 'in', ('todo', 'doing'))]):
                task = Maint.create({'mold_id': mold.id, 'trigger': 'shot', 'level': 'l1',
                                     'shots_at_trigger': mold.cycle_usage_count})
                msg += _(' 周期模次 %(c)s 已达保养阈值，自动生成保养任务 %(t)s。', c=mold.cycle_usage_count, t=task.name)
            mold.message_post(body=msg)
            if rec.order_id:
                rec.order_id.message_post(body=msg)
        return True

    def action_cancel(self):
        self.filtered(lambda r: r.state == 'draft').write({'state': 'cancel'})
        return True


class SnInjMold(models.Model):
    _inherit = 'sn.inj.mold'

    mold_state = fields.Selection(selection_add=[('loaned', '外借')], ondelete={'loaned': lambda recs: recs._compute_mold_state()})
    loan_id = fields.Many2one('sn.out.mold.loan', string='当前外借单', copy=False, readonly=True)
    loan_factory_id = fields.Many2one(related='loan_id.factory_id', string='外借代工厂', store=True)
    position_text = fields.Char(string='当前位置', compute='_compute_position')

    @api.depends('tooling_id.state', 'loan_id')
    def _compute_mold_state(self):
        super()._compute_mold_state()
        for mold in self:
            if mold.loan_id:
                mold.mold_state = 'loaned'

    @api.depends('loan_id', 'machine_id', 'location_id')
    def _compute_position(self):
        for mold in self:
            if mold.loan_id:
                mold.position_text = _('外借-%s', mold.loan_id.factory_id.name)
            elif mold.machine_id:
                mold.position_text = _('在机-%s', mold.machine_id.code)
            else:
                mold.position_text = mold.location_id.name or ''

    def _check_usable(self, action):
        for mold in self:
            if mold.loan_id:
                raise UserError(_('模具 %(m)s 已外借至 %(f)s（外借单 %(l)s）尚未归还，禁止%(a)s。',
                                  m=mold.sn, f=mold.loan_id.factory_id.name, l=mold.loan_id.name, a=action))
        return super()._check_usable(action)

    def _check_loanable(self):
        for mold in self:
            if mold.loan_id:
                raise UserError(_('模具 %(m)s 已外借至 %(f)s，不能重复借出。', m=mold.sn, f=mold.loan_id.factory_id.name))
            if mold.machine_id or mold.mold_state != 'in_stock' or mold.tooling_id.state != 'idle':
                raise UserError(_('模具 %(m)s 当前状态为「%(s)s」，须下机入库后才能外借。', m=mold.sn,
                                  s=dict(self._fields['mold_state'].selection).get(mold.mold_state)))
            mold._check_usable(_('外借'))
            busy = self.env['sn.inj.plan'].search([('mold_id', '=', mold.id), ('state', 'in', ('confirmed', 'running'))],
                                                  limit=1)
            if busy:
                raise UserError(_('模具 %(m)s 已排本厂计划 %(p)s，不能外借。', m=mold.sn, p=busy.name))
        return True


class SnInjPlan(models.Model):
    _inherit = 'sn.inj.plan'

    out_request_ids = fields.One2many('sn.out.request', 'plan_id', string='外发申请')

    def action_to_outsource(self):
        """排产计划转整单外发：带出产品、未完成数量、交期与模具，默认原因「机台满负荷」。"""
        self.ensure_one()
        if self.state not in ('draft', 'confirmed'):
            raise UserError(_('只有草稿/已下达的计划可以转外发。'))
        req = self.env['sn.out.request'].create({
            'source': 'plan', 'plan_id': self.id, 'customer_id': self.partner_id.id,
            'product_id': self.product_id.id, 'qty': self.planned_qty,
            'date_need': self.date_deadline or (self.date_end and self.date_end.date()) or fields.Date.context_today(self),
            'mold_id': self.mold_id.id, 'reason_type': 'load',
            'reason': _('注塑计划 %(p)s（机台 %(m)s）产能不足，整单外发。', p=self.name, m=self.machine_id.code),
        })
        req.action_eval_load()
        return {'type': 'ir.actions.act_window', 'res_model': 'sn.out.request', 'res_id': req.id, 'view_mode': 'form'}


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    out_request_ids = fields.One2many('sn.out.request', 'sale_order_id', string='外发申请')
    out_order_ids = fields.One2many('sn.out.order', 'sale_order_id', string='代工单')
    out_order_count = fields.Integer(string='代工单数', compute='_compute_out_count')

    def _compute_out_count(self):
        for so in self:
            so.out_order_count = len(so.out_order_ids)

    def action_to_outsource(self, reason_type='load', reason=False):
        """客户订单整单外发：按订单行（注塑件）生成外发申请并评估本厂负荷。"""
        self.ensure_one()
        if self.state not in ('sale',):
            raise UserError(_('客户订单确认后才能发起外发。'))
        Mold = self.env['sn.inj.mold']
        reqs = self.env['sn.out.request']
        for line in self.order_line.filtered(lambda l: l.product_id and not l.display_type):
            if self.env['sn.out.request'].search_count([('sale_line_id', '=', line.id), ('state', '!=', 'cancel')]):
                continue
            if not Mold.search_count([('product_ids', 'in', line.product_id.ids)]):
                continue
            reqs |= self.env['sn.out.request'].create({
                'source': 'sale', 'sale_order_id': self.id, 'sale_line_id': line.id,
                'customer_id': self.partner_id.id, 'product_id': line.product_id.id,
                'qty': int(line.product_uom_qty),
                'date_need': (self.commitment_date or self.date_order + timedelta(days=14)).date(),
                'reason_type': reason_type, 'reason': reason,
            })
        if not reqs:
            raise UserError(_('本订单没有可外发的注塑件，或已发起外发。'))
        if not self.env.context.get('out_skip_load'):
            reqs.action_eval_load()
        if len(reqs) == 1:
            return {'type': 'ir.actions.act_window', 'res_model': 'sn.out.request', 'res_id': reqs.id, 'view_mode': 'form'}
        return {'type': 'ir.actions.act_window', 'name': _('外发申请'), 'res_model': 'sn.out.request',
                'view_mode': 'list,form', 'domain': [('id', 'in', reqs.ids)]}

    def action_view_out_orders(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('代工单'), 'res_model': 'sn.out.order',
                'view_mode': 'list,form', 'domain': [('sale_order_id', '=', self.id)]}
