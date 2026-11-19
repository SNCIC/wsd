import pytz
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

REQUIRE_PARAM = 'sn_wsd_piece_time.require_hours'

TIME_KEYS = {'x_date_start', 'x_date_end', 'x_duration_hours', 'x_hours_alloc', 'x_timer_seconds'}


def _require_hours(env):
    return env['ir.config_parameter'].sudo().get_param(REQUIRE_PARAM, '0') == '1'


class MesOperationReport(models.Model):
    """报工同时记录数量和工时。

    工时三种来源（优先级从高到低）：工位终端计时累计秒数（开工/暂停/继续/完工）
    → 开工/完工时间 → 手工填写工时。多名参与人时，每人工时按在岗时段记录，
    未填在岗时段的按整段时长；也可选「按比例」把总人工工时按绩效比例分配。
    报工落库后为每位参与人生成工时记录（工单工时统计），并推进制令单 / 工序的
    实际开工、完工时间。计件结算单确认后工时冻结；月份关账后不能修改。"""
    _inherit = 'sn.wsd.mes.operation.report'

    x_date_start = fields.Datetime(string='开工时间')
    x_date_end = fields.Datetime(string='完工时间')
    x_timer_seconds = fields.Integer(string='终端计时(秒)', readonly=True)
    x_duration_hours = fields.Float(
        string='报工时长(小时)', digits=(10, 2), compute='_compute_duration', store=True,
        readonly=False)
    x_hours_source = fields.Selection([
        ('terminal', '工位终端计时'), ('workbench', '日报工录入'),
        ('period', '开工/完工时间'), ('manual', '手工填写'),
    ], string='工时来源')
    x_hours_alloc = fields.Selection(
        [('duty', '按在岗时段'), ('ratio', '按比例')], string='多人工时记录方式',
        default='duty')
    x_man_hours = fields.Float(
        string='人工工时(小时)', digits=(10, 2), compute='_compute_man_hours', store=True)
    x_headcount = fields.Integer(string='人数', compute='_compute_man_hours', store=True)
    x_std_seconds = fields.Float(
        string='标准节拍(秒/件)', related='route_operation_id.time_cycle_manual')
    x_std_hours = fields.Float(
        string='标准工时(小时)', digits=(10, 2), compute='_compute_std', store=True)
    x_efficiency = fields.Float(
        string='工时效率(%)', digits=(6, 1), compute='_compute_std', store=True,
        aggregator='avg', help='标准工时 ÷ 实际人工工时 × 100')
    x_uph = fields.Float(
        string='人均小时产出(件)', digits=(10, 1), compute='_compute_std', store=True,
        aggregator='avg', help='合格数 ÷ 人工工时')
    x_rate_type = fields.Selection(
        [('piece', '计件'), ('hour', '计时')], string='计酬方式', compute='_compute_rate_info')
    x_unit_price = fields.Float(string='单价', digits=(12, 4), compute='_compute_rate_info')
    x_wage_amount = fields.Float(string='预计工资(元)', digits=(12, 2), compute='_compute_rate_info')
    time_entry_ids = fields.One2many('sn.wsd.time.entry', 'operation_report_id', string='工时记录')

    @api.depends('mes_order_id.name', 'route_operation_id', 'reported_at')
    def _compute_display_name(self):
        for rep in self:
            op = rep.route_operation_id.operation_id.name or ''
            rep.display_name = '%s / %s / 报工#%s' % (rep.mes_order_id.name or '', op, rep.id or '')

    @api.model
    def _sn_post_install_labels(self):
        """中文界面：计件模块根菜单显示为「计件计时」（只写 zh_CN 译文，不改计件模块文件）。"""
        menu = self.env.ref('sn_wsd_piece_rate.menu_sn_wsd_piece_rate_root', raise_if_not_found=False)
        if menu:
            menu.with_context(lang='zh_CN').name = '计件计时'
        return True

    @api.depends('x_timer_seconds', 'x_date_start', 'x_date_end')
    def _compute_duration(self):
        for rep in self:
            if rep.x_timer_seconds:
                rep.x_duration_hours = round(rep.x_timer_seconds / 3600.0, 4)
            elif rep.x_date_start and rep.x_date_end and rep.x_date_end > rep.x_date_start:
                rep.x_duration_hours = round(
                    (rep.x_date_end - rep.x_date_start).total_seconds() / 3600.0, 4)
            else:
                rep.x_duration_hours = rep.x_duration_hours or 0.0

    @api.depends('participant_ids.x_work_hours', 'x_duration_hours')
    def _compute_man_hours(self):
        for rep in self:
            parts = rep.participant_ids
            rep.x_headcount = len(parts) or (1 if rep.x_duration_hours else 0)
            rep.x_man_hours = round(sum(parts.mapped('x_work_hours')), 4) if parts \
                else rep.x_duration_hours

    @api.depends('qty_ok', 'x_man_hours', 'route_operation_id.time_cycle_manual')
    def _compute_std(self):
        for rep in self:
            std = rep.qty_ok * (rep.route_operation_id.time_cycle_manual or 0.0) / 3600.0
            rep.x_std_hours = round(std, 4)
            rep.x_efficiency = round(std / rep.x_man_hours * 100.0, 1) if rep.x_man_hours else 0.0
            rep.x_uph = round(rep.qty_ok / rep.x_man_hours, 1) if rep.x_man_hours else 0.0

    def _compute_rate_info(self):
        Rate = self.env['sn.wsd.piece.rate'].sudo()
        for rep in self:
            rate = Rate.search([
                ('company_id', '=', rep.company_id.id),
                ('product_id', '=', rep.mes_order_id.product_id.id),
                ('operation_id', '=', rep.route_operation_id.operation_id.id),
            ], limit=1)
            rep.x_rate_type = rate.x_rate_type or 'piece'
            rep.x_unit_price = rate.price
            base = rep.x_man_hours if rep.x_rate_type == 'hour' else rep.qty_ok
            rep.x_wage_amount = round(base * rate.price, 2)

    @api.constrains('x_date_start', 'x_date_end')
    def _check_window(self):
        for rep in self:
            if rep.x_date_start and rep.x_date_end and rep.x_date_end <= rep.x_date_start:
                raise ValidationError(_('完工时间必须晚于开工时间。'))

    # ------------------------------------------------------------------
    def _report_date(self):
        self.ensure_one()
        dt = self.x_date_end or self.reported_at
        return self.env['sn.wsd.time.entry']._local_date(dt) if dt else fields.Date.context_today(self)

    def write(self, vals):
        if TIME_KEYS & set(vals) and not self.env.context.get('sn_time_applying'):
            CloseLog = self.env['sn.wsd.piece.close.log']
            for rep in self:
                CloseLog._assert_month_open(rep.company_id, rep._report_date())
            self._check_allocation_editable()
        res = super().write(vals)
        if TIME_KEYS & set(vals) and not self.env.context.get('sn_time_applying'):
            self._sync_time_entries()
        return res

    def _apply_report_allocation(self, participant_vals, team_id):
        res = super()._apply_report_allocation(participant_vals, team_id)
        window = self.env.context.get('sn_time_window')
        if window:
            self.with_context(sn_time_applying=True)._apply_time_window(window)
            self._sync_time_entries()
        return res

    def _apply_time_window(self, window):
        """落库报工的工时：时段 / 计时秒数 / 手填工时 + 参与人在岗时段或工时。"""
        self.ensure_one()
        start, end = window.get('start'), window.get('end')
        hours = window.get('hours') or 0.0
        seconds = window.get('seconds') or 0
        if not end:
            end = self.reported_at or fields.Datetime.now()
        if not start:
            span = (seconds / 3600.0) if seconds else hours
            if span <= 0:
                raise ValidationError(_('报工必须记录工时：请填写开工/完工时间或工时。'))
            start = end - timedelta(hours=span)
        vals = {'x_date_start': start, 'x_date_end': end,
                'x_hours_source': window.get('source') or 'period',
                'x_hours_alloc': window.get('alloc') or 'duty'}
        if seconds:
            vals['x_timer_seconds'] = seconds
        self.write(vals)
        duties = window.get('duties') or {}
        hours_by_emp = window.get('hours_by_emp') or {}
        for part in self.participant_ids:
            emp = part.employee_id.id
            pvals = {}
            if emp in duties:
                pvals.update({'x_duty_start': duties[emp][0], 'x_duty_end': duties[emp][1]})
            if pvals:
                part.write(pvals)
            if hours_by_emp.get(emp):
                part.write({'x_hours_input': hours_by_emp[emp]})
        if self.x_rate_type == 'hour' and self.participant_ids:
            self.action_ratio_by_hours()

    def action_ratio_by_hours(self):
        """计时工序（或手动点按钮）：绩效比例 = 本人工时 ÷ 人工工时合计。"""
        Settlement = self.env['sn.wsd.piece.settlement']
        for rep in self:
            parts = rep.participant_ids.sorted('sequence')
            hours = [p.x_work_hours for p in parts]
            if not parts or sum(hours) <= 0:
                raise UserError(_('请先记录参与人工时。'))
            ratios = Settlement._distribute_ratios(hours)
            for part, ratio in zip(parts, ratios):
                if abs(part.performance_ratio - ratio) > 0.00001:
                    part.performance_ratio = ratio
        return True

    def _sync_time_entries(self):
        """按报工的时段和参与人工时重建工时记录（结算确认后不可调用：上游已拦截）。"""
        Entry = self.env['sn.wsd.time.entry'].with_context(sn_time_sync=True)
        for rep in self:
            if not rep.x_date_end or not rep.x_duration_hours:
                continue
            rep.time_entry_ids.with_context(sn_time_sync=True).unlink()
            category = self.env.context.get('sn_time_category') or 'production'
            parts = rep.participant_ids.sorted('sequence')
            rows = []
            if parts:
                for part in parts:
                    start = part.x_duty_start or rep.x_date_start
                    end = part.x_duty_end or rep.x_date_end
                    rows.append((part.employee_id, start, end, part.x_work_hours,
                                 rep.qty_ok * (part.performance_ratio or 0.0) / 100.0))
            else:
                emp = rep.reported_by.employee_id if rep.reported_by else False
                if emp:
                    rows.append((emp, rep.x_date_start, rep.x_date_end,
                                 rep.x_duration_hours, rep.qty_ok))
            src = {'terminal': 'terminal', 'workbench': 'workbench'}.get(rep.x_hours_source, 'report')
            for emp, start, end, hours, qty in rows:
                if not hours:
                    continue
                Entry.create({
                    'company_id': rep.company_id.id,
                    'employee_id': emp.id,
                    'category': category,
                    'mes_order_id': rep.mes_order_id.id,
                    'route_operation_id': rep.route_operation_id.id,
                    'operation_report_id': rep.id,
                    'timer_id': self.env.context.get('sn_timer_id') or False,
                    'date_start': start,
                    'date_end': end,
                    'hours': hours,
                    'qty_ok': round(qty, 2),
                    'source': src,
                    'state': 'confirmed',
                })


class MesOperationReportParticipant(models.Model):
    _inherit = 'sn.wsd.mes.operation.report.participant'

    x_duty_start = fields.Datetime(string='在岗开始')
    x_duty_end = fields.Datetime(string='在岗结束')
    x_hours_input = fields.Float(string='手填工时', digits=(10, 2),
                                 help='填写后以此为准（日报工直接录入本人工时）。')
    x_work_hours = fields.Float(
        string='工时(小时)', digits=(10, 2), compute='_compute_work_hours', store=True)

    @api.depends('x_hours_input', 'x_duty_start', 'x_duty_end', 'report_id.x_duration_hours',
                 'report_id.x_hours_alloc', 'performance_ratio')
    def _compute_work_hours(self):
        for part in self:
            rep = part.report_id
            if part.x_hours_input:
                part.x_work_hours = part.x_hours_input
            elif part.x_duty_start and part.x_duty_end and part.x_duty_end > part.x_duty_start:
                part.x_work_hours = round(
                    (part.x_duty_end - part.x_duty_start).total_seconds() / 3600.0, 4)
            elif rep.x_hours_alloc == 'ratio':
                part.x_work_hours = round(
                    rep.x_duration_hours * len(rep.participant_ids)
                    * (part.performance_ratio or 0.0) / 100.0, 4)
            else:
                part.x_work_hours = rep.x_duration_hours

    @api.constrains('x_duty_start', 'x_duty_end')
    def _check_duty(self):
        for part in self:
            if part.x_duty_start and part.x_duty_end and part.x_duty_end <= part.x_duty_start:
                raise ValidationError(_('在岗结束必须晚于在岗开始。'))

    _SYNC_KEYS = {'x_duty_start', 'x_duty_end', 'x_hours_input', 'employee_id', 'performance_ratio'}

    @api.model_create_multi
    def create(self, vals_list):
        parts = super().create(vals_list)
        if not self.env.context.get('sn_time_applying'):
            parts.mapped('report_id').filtered('x_date_end')._sync_time_entries()
        return parts

    def write(self, vals):
        res = super().write(vals)
        if self._SYNC_KEYS & set(vals) and not self.env.context.get('sn_time_applying'):
            self.mapped('report_id')._sync_time_entries()
        return res

    def unlink(self):
        reports = self.mapped('report_id')
        res = super().unlink()
        if not self.env.context.get('sn_time_applying'):
            reports.exists().filtered('x_date_end')._sync_time_entries()
        return res


class MesOrderRouteOperation(models.Model):
    _inherit = 'sn.wsd.mes.order.route.operation'

    x_act_start = fields.Datetime(string='实际开工', readonly=True, copy=False)
    x_act_end = fields.Datetime(string='实际完工', readonly=True, copy=False)
    x_act_hours = fields.Float(string='实际人工工时', digits=(10, 2), readonly=True, copy=False)


class MesOrder(models.Model):
    _inherit = 'sn.wsd.mes.order'

    time_entry_ids = fields.One2many('sn.wsd.time.entry', 'mes_order_id', string='工时记录')
    x_labor_start = fields.Datetime(string='实际开工（工时）', readonly=True, copy=False)
    x_labor_end = fields.Datetime(string='实际完工（工时）', readonly=True, copy=False)
    x_labor_hours = fields.Float(string='人工工时', digits=(10, 2), readonly=True, copy=False)

    def _sn_recompute_labor_actuals(self):
        """按已确认工时推进制令单与工序的实际开工 / 完工时间和人工工时（不计停机）。"""
        if not self:
            return
        self.env['sn.wsd.time.entry'].flush_model()
        cr = self.env.cr
        cr.execute("""
            UPDATE sn_wsd_mes_order o SET
                   x_labor_start = s.mn, x_labor_end = s.mx, x_labor_hours = s.h
              FROM (SELECT o2.id, MIN(e.date_start) mn, MAX(e.date_end) mx,
                           COALESCE(SUM(e.hours), 0) h
                      FROM sn_wsd_mes_order o2
                      LEFT JOIN sn_wsd_time_entry e ON e.mes_order_id = o2.id
                           AND e.state = 'confirmed' AND e.category != 'downtime'
                     WHERE o2.id IN %s GROUP BY o2.id) s
             WHERE o.id = s.id
        """, (tuple(self.ids),))
        cr.execute("""
            UPDATE sn_wsd_mes_order_route_operation r SET
                   x_act_start = s.mn, x_act_end = s.mx, x_act_hours = s.h
              FROM (SELECT r2.id, MIN(e.date_start) mn, MAX(e.date_end) mx,
                           COALESCE(SUM(e.hours), 0) h
                      FROM sn_wsd_mes_order_route_operation r2
                      LEFT JOIN sn_wsd_time_entry e ON e.route_operation_id = r2.id
                           AND e.state = 'confirmed' AND e.category != 'downtime'
                     WHERE r2.mes_order_id IN %s GROUP BY r2.id) s
             WHERE r.id = s.id
        """, (tuple(self.ids),))
        self.invalidate_recordset(['x_labor_start', 'x_labor_end', 'x_labor_hours'])
        self.env['sn.wsd.mes.order.route.operation'].invalidate_model(
            ['x_act_start', 'x_act_end', 'x_act_hours'])

    def report_operation_qty(self, route_operation, qty_ok, qty_ng=0.0, qty_scrap=0.0,
                             scrap_reason=False, participant_vals=None, team_id=False):
        ctx = self.env.context
        window = None
        wb = ctx.get('sn_workbench_time')
        if wb:
            window = wb.get('%s-%s' % (self.id, route_operation.id))
        if not window and ctx.get('sn_timer_window'):
            window = ctx['sn_timer_window']
            if not participant_vals and window.get('participants'):
                participant_vals = window['participants']
        target = self
        if window:
            target = self.with_context(sn_time_window=window)
        return super(MesOrder, target).report_operation_qty(
            route_operation, qty_ok, qty_ng=qty_ng, qty_scrap=qty_scrap,
            scrap_reason=scrap_reason, participant_vals=participant_vals, team_id=team_id)

    def report_operation_with_time(self, route_operation, qty_ok, date_start=False, date_end=False,
                                   hours=0.0, participant_vals=None, qty_ng=0.0, qty_scrap=0.0,
                                   scrap_reason=False, team_id=False, alloc='duty',
                                   source='period'):
        """带工时的报工（日报工 / 后台 / 演示造数统一入口）。

        participant_vals 每行可带 duty_start / duty_end（本人在岗时段）或 work_hours（本人工时）。"""
        self.ensure_one()
        if not (date_start and date_end) and not hours:
            raise ValidationError(_('报工必须记录工时：请填写开工/完工时间或工时。'))
        duties, hours_by_emp, clean = {}, {}, []
        for line in participant_vals or []:
            line = dict(line)
            ds, de = line.pop('duty_start', None), line.pop('duty_end', None)
            wh = line.pop('work_hours', None)
            if ds and de:
                duties[line['employee_id']] = (fields.Datetime.to_datetime(ds),
                                               fields.Datetime.to_datetime(de))
            if wh:
                hours_by_emp[line['employee_id']] = wh
            clean.append(line)
        window = {
            'start': fields.Datetime.to_datetime(date_start) if date_start else False,
            'end': fields.Datetime.to_datetime(date_end) if date_end else False,
            'hours': hours, 'duties': duties, 'hours_by_emp': hours_by_emp,
            'alloc': alloc, 'source': source,
        }
        return self.with_context(sn_time_window=window).report_operation_qty(
            route_operation, qty_ok, qty_ng=qty_ng, qty_scrap=qty_scrap,
            scrap_reason=scrap_reason, participant_vals=clean, team_id=team_id)


class PieceCloseWizard(models.TransientModel):
    _inherit = 'sn.wsd.piece.close.wizard'

    time_pending_count = fields.Integer(string='待确认补录工时', compute='_compute_time_pending')

    @api.depends('company_id', 'period')
    def _compute_time_pending(self):
        for wizard in self:
            wizard.time_pending_count = 0
            if wizard.period and len(wizard.period) == 7:
                date_from = fields.Date.to_date(wizard.period + '-01')
                wizard.time_pending_count = self.env['sn.wsd.time.entry'].search_count([
                    ('company_id', '=', wizard.company_id.id),
                    ('date', '>=', date_from),
                    ('date', '<=', fields.Date.end_of(date_from, 'month')),
                    ('state', '=', 'to_confirm')])


class PieceWorkbench(models.TransientModel):
    """日报工工作台：每行可填开工/完工时间或工时，参与人可填本人工时。"""
    _inherit = 'sn.wsd.piece.settlement.generate.wizard'

    @api.model
    def get_workbench_data(self, workshop_id=False, production_line_id=False, mes_order_id=False):
        data = super().get_workbench_data(workshop_id, production_line_id, mes_order_id)
        for line in data.get('lines', []):
            line.update({'x_date_start': '', 'x_date_end': '', 'x_hours': 0.0})
            for p in line.get('participants', []):
                p['x_work_hours'] = 0.0
        data['require_hours'] = _require_hours(self.env)
        return data

    @api.model
    def _local_to_utc(self, value):
        if not value:
            return False
        value = value.replace('T', ' ')
        if len(value) == 16:
            value += ':00'
        naive = fields.Datetime.to_datetime(value)
        tz = pytz.timezone(self.env.user.tz or 'Asia/Shanghai')
        return tz.localize(naive).astimezone(pytz.utc).replace(tzinfo=None)

    @api.model
    def submit_workbench(self, lines_payload):
        windows = {}
        require = _require_hours(self.env)
        for payload in lines_payload or []:
            if not (payload.get('qty_ok') or payload.get('qty_ng') or payload.get('qty_scrap')):
                continue
            start = self._local_to_utc(payload.get('x_date_start'))
            end = self._local_to_utc(payload.get('x_date_end'))
            hours = float(payload.get('x_hours') or 0.0)
            if not ((start and end) or hours):
                if require:
                    raise ValidationError(_(
                        '制令单 %s 的报工未填写工时：请填写开工/完工时间或工时。',
                        payload.get('order_name') or payload.get('mes_order_id')))
                continue
            hours_by_emp = {p['employee_id']: float(p.get('x_work_hours') or 0.0)
                            for p in payload.get('participants') or []
                            if float(p.get('x_work_hours') or 0.0) > 0}
            windows['%s-%s' % (payload['mes_order_id'], payload['route_operation_id'])] = {
                'start': start, 'end': end, 'hours': hours if not (start and end) else 0.0,
                'hours_by_emp': hours_by_emp, 'source': 'workbench', 'alloc': 'duty',
            }
        return super(PieceWorkbench, self.with_context(sn_workbench_time=windows)).submit_workbench(
            lines_payload)
