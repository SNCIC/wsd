from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

CATEGORY_SELECTION = [
    ('production', '生产'),
    ('rework', '返修'),
    ('trial', '试产/调试'),
    ('downtime', '停机/异常'),
]
SOURCE_SELECTION = [
    ('terminal', '工位终端计时'),
    ('workbench', '日报工录入'),
    ('report', '报工开工/完工'),
    ('station', '过站计时'),
    ('manual', '手工补录'),
]
DOWNTIME_REASON_SELECTION = [
    ('equipment', '设备故障'),
    ('material', '待料'),
    ('changeover', '换线/换型'),
    ('quality', '质量待判'),
    ('power', '停电/停气'),
    ('other', '其他'),
]


class SnWsdTimeEntry(models.Model):
    """工时记录：每次报工（工序报工、日报工、工位终端、过站计时）为每位参与人
    写一条，是工时分析的唯一事实来源，相当于工单的工时统计。

    - 防重复：同一员工同一时段只能有一条有效工时；
    - 冻结：来源报工的计件结算单确认后，工时随之冻结；所在月份关账后不可新增、
      修改、删除；
    - 手工补录必须填原因，经班组长（或计件管理员）确认后才计入分析；
    - 停机/异常工时单列，只用于分析，不计薪。
    """
    _name = 'sn.wsd.time.entry'
    _description = '工时记录'
    _inherit = ['mail.thread']
    _order = 'date_start desc, id desc'
    _check_company_auto = True

    name = fields.Char(string='工时单号', default=lambda self: _('新建'), copy=False, readonly=True)
    company_id = fields.Many2one(
        'res.company', string='公司', default=lambda self: self.env.company,
        required=True, index=True)
    employee_id = fields.Many2one(
        'hr.employee', string='员工', required=True, index=True, check_company=True,
        tracking=True)
    employee_code = fields.Char(related='employee_id.barcode', string='工号', store=True)
    category = fields.Selection(
        CATEGORY_SELECTION, string='工时类别', required=True, default='production',
        tracking=True, index=True)
    mes_order_id = fields.Many2one('sn.wsd.mes.order', string='制令单', index=True, tracking=True)
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation', string='工序', index=True,
        domain="[('mes_order_id', '=', mes_order_id)]")
    product_id = fields.Many2one(related='mes_order_id.product_id', string='产品', store=True)
    production_line_id = fields.Many2one(
        related='mes_order_id.production_line_id', string='线体', store=True)
    date_start = fields.Datetime(string='开始时间', required=True, tracking=True)
    date_end = fields.Datetime(string='结束时间', required=True, tracking=True)
    hours = fields.Float(
        string='工时(小时)', digits=(10, 2), compute='_compute_hours', store=True,
        readonly=False, tracking=True,
        help='默认 = 结束 − 开始；按比例分配或终端暂停扣除时可小于时段长度。')
    qty_ok = fields.Float(string='合格数', digits=(12, 2),
                          help='本条工时对应的合格数（报工按参与人比例折算；过站计时为时段内合格过站数）。')
    date = fields.Date(string='业务日期', compute='_compute_date', store=True, index=True)
    source = fields.Selection(SOURCE_SELECTION, string='工时来源', required=True,
                              default='manual', readonly=True, tracking=True)
    operation_report_id = fields.Many2one(
        'sn.wsd.mes.operation.report', string='来源报工', index=True,
        ondelete='cascade', readonly=True)
    timer_id = fields.Many2one('sn.wsd.work.timer', string='来源计时', index=True, readonly=True)
    exception_id = fields.Many2one('sn.wsd.exception.ticket', string='关联异常单', index=True)
    downtime_reason = fields.Selection(DOWNTIME_REASON_SELECTION, string='停机原因')
    manual_reason = fields.Text(string='补录原因', tracking=True)
    state = fields.Selection(
        [('to_confirm', '待班组长确认'), ('confirmed', '已确认'), ('cancelled', '已作废')],
        string='状态', default='confirmed', required=True, tracking=True, index=True)
    confirmed_by = fields.Many2one('res.users', string='确认人', readonly=True, copy=False)
    confirmed_at = fields.Datetime(string='确认时间', readonly=True, copy=False)
    paid = fields.Boolean(string='计入人工工时', compute='_compute_paid', store=True,
                          help='停机/异常工时不计薪、不计入人工工时，只用于分析。')
    frozen_label = fields.Char(string='结算状态', compute='_compute_frozen')

    @api.depends('date_start', 'date_end')
    def _compute_hours(self):
        for entry in self:
            if entry.date_start and entry.date_end and entry.date_end > entry.date_start:
                entry.hours = round((entry.date_end - entry.date_start).total_seconds() / 3600.0, 4)
            else:
                entry.hours = 0.0

    @api.depends('date_start')
    def _compute_date(self):
        for entry in self:
            entry.date = entry._local_date(entry.date_start) if entry.date_start else False

    @api.depends('category')
    def _compute_paid(self):
        for entry in self:
            entry.paid = entry.category != 'downtime'

    def _compute_frozen(self):
        for entry in self:
            sts = entry.operation_report_id.piece_settlement_ids.filtered(
                lambda s: s.state != 'void')
            if any(s.state == 'confirmed' for s in sts):
                entry.frozen_label = '已冻结'
            elif sts:
                entry.frozen_label = '结算草稿'
            elif entry.operation_report_id:
                entry.frozen_label = '未结算'
            else:
                entry.frozen_label = '—'

    def _tz(self):
        return self.env.context.get('tz') or self.env.user.tz or 'Asia/Shanghai'

    def _local_date(self, dt):
        if isinstance(dt, str):
            dt = fields.Datetime.to_datetime(dt)
        return fields.Datetime.context_timestamp(self.with_context(tz=self._tz()), dt).date()

    def _fmt(self, dt):
        if not dt:
            return ''
        return fields.Datetime.context_timestamp(
            self.with_context(tz=self._tz()), dt).strftime('%m-%d %H:%M')

    # ------------------------------------------------------------------
    @api.constrains('date_start', 'date_end', 'hours', 'category', 'mes_order_id',
                    'exception_id', 'downtime_reason', 'source', 'manual_reason')
    def _check_values(self):
        for entry in self:
            if entry.date_end <= entry.date_start:
                raise ValidationError(_('结束时间必须晚于开始时间。'))
            span = (entry.date_end - entry.date_start).total_seconds() / 3600.0
            if span > 16:
                raise ValidationError(_('单条工时不能超过 16 小时，请拆分或核对时间。'))
            if entry.hours <= 0:
                raise ValidationError(_('工时必须大于 0。'))
            if entry.category in ('production', 'rework') and not entry.mes_order_id:
                raise ValidationError(_('生产和返修工时必须关联制令单。'))
            if entry.category == 'downtime' and not (entry.exception_id or entry.downtime_reason):
                raise ValidationError(_('停机/异常工时必须关联异常单或选择停机原因。'))
            if entry.source == 'manual' and not (entry.manual_reason or '').strip():
                raise ValidationError(_('手工补录工时必须填写补录原因。'))

    @api.constrains('employee_id', 'date_start', 'date_end', 'state')
    def _check_overlap(self):
        self.flush_model()
        for entry in self.filtered(lambda e: e.state != 'cancelled'):
            self.env.cr.execute("""
                SELECT name, date_start, date_end FROM sn_wsd_time_entry
                 WHERE employee_id = %s AND id != %s AND state != 'cancelled'
                   AND date_start < %s AND date_end > %s
                 LIMIT 1
            """, (entry.employee_id.id, entry.id, entry.date_end, entry.date_start))
            row = self.env.cr.fetchone()
            if row:
                raise ValidationError(_(
                    '员工「%(emp)s」在 %(s)s – %(e)s 已有工时记录 %(name)s，'
                    '同一员工同一时段不能重复记工时。',
                    emp=entry.employee_id.name, name=row[0],
                    s=entry._fmt(row[1]), e=entry._fmt(row[2])))

    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        CloseLog = self.env['sn.wsd.piece.close.log']
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('新建'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.wsd.time.entry') or _('新建')
            if vals.get('date_start'):
                company = self.env['res.company'].browse(
                    vals.get('company_id') or self.env.company.id)
                CloseLog._assert_month_open(company, self._local_date(vals['date_start']))
            if vals.get('source', 'manual') == 'manual':
                vals['state'] = 'to_confirm'
        entries = super().create(vals_list)
        entries._touch_actuals()
        return entries

    _STATE_ONLY = {'state', 'confirmed_by', 'confirmed_at'}

    def _assert_editable(self, vals=None):
        CloseLog = self.env['sn.wsd.piece.close.log']
        for entry in self:
            CloseLog._assert_month_open(entry.company_id, entry.date)
            if vals and vals.get('date_start'):
                CloseLog._assert_month_open(entry.company_id, entry._local_date(vals['date_start']))
            if entry.operation_report_id and not self.env.context.get('sn_time_sync'):
                entry.operation_report_id._check_allocation_editable()

    def write(self, vals):
        if set(vals) - {'message_main_attachment_id'}:
            self._assert_editable(vals)
            for entry in self:
                if entry.state == 'confirmed' and entry.source == 'manual' \
                        and set(vals) - self._STATE_ONLY:
                    raise UserError(_('补录工时已经班组长确认，不能再修改；如有错误请作废后重新补录。'))
        res = super().write(vals)
        if {'date_start', 'date_end', 'state'} & set(vals):
            self._touch_actuals()
        return res

    def unlink(self):
        self._assert_editable()
        orders = self.mapped('mes_order_id')
        res = super().unlink()
        orders._sn_recompute_labor_actuals()
        return res

    def _touch_actuals(self):
        self.mapped('mes_order_id')._sn_recompute_labor_actuals()

    # ------------------------------------------------------------------
    def _leader_users(self):
        self.ensure_one()
        members = self.env['sn.mrp.team.member'].sudo().search([
            ('employee_id', '=', self.employee_id.id)])
        users = self.env['res.users']
        for member in members:
            leader = member.team_id.leader_member_id.employee_id
            if leader and leader.user_id:
                users |= leader.user_id
        return users

    def action_leader_confirm(self):
        """班组长确认补录：只能确认本班组成员，不能确认自己的补录。"""
        user = self.env.user
        is_manager = user.has_group('sn_wsd_piece_rate.group_piece_rate_manager')
        for entry in self:
            if entry.state != 'to_confirm':
                raise UserError(_('工时记录 %s 不是待确认状态。', entry.name))
            if entry.employee_id.user_id == user and not is_manager:
                raise UserError(_('不能确认自己的补录工时，请由班组长或管理员确认。'))
            if not is_manager and user not in entry._leader_users():
                raise UserError(_(
                    '只有员工「%s」所在班组的班组长或计件管理员可以确认补录工时。',
                    entry.employee_id.name))
        self.write({'state': 'confirmed', 'confirmed_by': user.id,
                    'confirmed_at': fields.Datetime.now()})
        for entry in self:
            entry.message_post(body=_('补录工时已由 %s 确认。', user.name))
        return True

    def action_cancel(self):
        for entry in self:
            if entry.operation_report_id:
                raise UserError(_('报工生成的工时请在报工记录上更正，不能单独作废。'))
        self.write({'state': 'cancelled'})
        return True

    @api.onchange('exception_id')
    def _onchange_exception_id(self):
        if self.exception_id and self.exception_id.mes_order_id and not self.mes_order_id:
            self.mes_order_id = self.exception_id.mes_order_id
