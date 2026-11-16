from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .report import _require_hours


class SnWsdWorkTimer(models.Model):
    """工位终端计时：开工 → 暂停 → 继续 → 完工，按累计秒数计算工时。

    - 同一员工同一时刻只能有一个计时在进行（计时中）；
    - 报工模式：完工即报工（录入合格/不良/报废），累计工时写入报工，并为
      操作员和同岗人员各生成一条工时记录；
    - 过站模式：完工时按计时时段内本工序的合格过站数生成工时记录（件数 + 工时）。
    """
    _name = 'sn.wsd.work.timer'
    _description = '工位计时'
    _order = 'id desc'
    _check_company_auto = True

    name = fields.Char(string='计时单号', default=lambda self: _('新建'), readonly=True, copy=False)
    company_id = fields.Many2one('res.company', string='公司', default=lambda self: self.env.company,
                                 required=True, index=True)
    employee_id = fields.Many2one('hr.employee', string='操作员', required=True, index=True,
                                  check_company=True)
    participant_ids = fields.Many2many('hr.employee', 'sn_wsd_work_timer_employee_rel',
                                       'timer_id', 'employee_id', string='同岗人员')
    mes_order_id = fields.Many2one('sn.wsd.mes.order', string='制令单', required=True, index=True)
    route_operation_id = fields.Many2one('sn.wsd.mes.order.route.operation', string='工序',
                                         required=True, index=True)
    workcenter_id = fields.Many2one('mrp.workcenter', string='工位')
    manage_mode = fields.Selection(related='mes_order_id.x_manage_mode', string='管理模式')
    state = fields.Selection([
        ('running', '计时中'), ('paused', '已暂停'), ('done', '已完工'), ('cancelled', '已取消'),
    ], string='计时状态', default='running', required=True, index=True)
    timer_seconds = fields.Integer(string='累计秒数', readonly=True)
    timer_resume_at = fields.Datetime(string='本段开始', readonly=True)
    date_start = fields.Datetime(string='开工时间', readonly=True)
    date_end = fields.Datetime(string='完工时间', readonly=True)
    pause_count = fields.Integer(string='暂停次数', readonly=True)
    hours = fields.Float(string='工时(小时)', digits=(10, 2), compute='_compute_hours', store=True)
    elapsed_display = fields.Char(string='已计时', compute='_compute_elapsed')
    report_id = fields.Many2one('sn.wsd.mes.operation.report', string='报工记录', readonly=True)
    qty_ok = fields.Float(string='合格数', readonly=True)
    time_entry_ids = fields.One2many('sn.wsd.time.entry', 'timer_id', string='工时记录')

    @api.depends('timer_seconds')
    def _compute_hours(self):
        for t in self:
            t.hours = round(t.timer_seconds / 3600.0, 4)

    def _live_seconds(self, now=None):
        self.ensure_one()
        secs = self.timer_seconds
        if self.state == 'running' and self.timer_resume_at:
            secs += int(((now or fields.Datetime.now()) - self.timer_resume_at).total_seconds())
        return secs

    def _compute_elapsed(self):
        for t in self:
            s = t._live_seconds()
            t.elapsed_display = '%02d:%02d:%02d' % (s // 3600, s % 3600 // 60, s % 60)

    @api.constrains('state', 'employee_id', 'participant_ids')
    def _check_single_running(self):
        for t in self.filtered(lambda r: r.state == 'running'):
            people = t.employee_id | t.participant_ids
            others = self.search([('state', '=', 'running'), ('id', '!=', t.id)])
            for other in others:
                clash = people & (other.employee_id | other.participant_ids)
                if clash:
                    raise ValidationError(_(
                        '「%(emp)s」已有进行中的计时（%(name)s：%(order)s / %(op)s），'
                        '同一人同一时间只能有一个计时在进行，请先暂停或完工。',
                        emp=clash[0].name, name=other.name, order=other.mes_order_id.name,
                        op=other.route_operation_id.display_label))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('新建'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.wsd.work.timer') or _('新建')
        return super().create(vals_list)

    # ------------------------------------------------------------------
    @api.model
    def start(self, employee, mes_order, route_operation, participants=None,
              workcenter=None, at=None):
        """开工：开始计时。"""
        if mes_order.state in ('done', 'cancelled'):
            raise UserError(_('制令单 %s 已完工或取消，不能开工计时。', mes_order.name))
        now = at or fields.Datetime.now()
        return self.create({
            'company_id': mes_order.company_id.id,
            'employee_id': employee.id,
            'participant_ids': [(6, 0, (participants or employee.browse()).ids)],
            'mes_order_id': mes_order.id,
            'route_operation_id': route_operation.id,
            'workcenter_id': workcenter.id if workcenter else False,
            'state': 'running',
            'timer_resume_at': now,
            'date_start': now,
        })

    def action_pause(self, at=None):
        for t in self:
            if t.state != 'running':
                raise UserError(_('只有计时中的记录可以暂停。'))
            now = at or fields.Datetime.now()
            t.write({'state': 'paused', 'timer_seconds': t._live_seconds(now),
                     'timer_resume_at': False, 'pause_count': t.pause_count + 1})
        return True

    def action_resume(self, at=None):
        for t in self:
            if t.state != 'paused':
                raise UserError(_('只有已暂停的记录可以继续。'))
            t.write({'state': 'running', 'timer_resume_at': at or fields.Datetime.now()})
        return True

    def _stop(self, at=None):
        self.ensure_one()
        if self.state not in ('running', 'paused'):
            raise UserError(_('计时 %s 已结束。', self.name))
        now = at or fields.Datetime.now()
        secs = self._live_seconds(now)
        if secs <= 0:
            raise UserError(_('计时时长为 0，不能完工。'))
        self.write({'timer_seconds': secs, 'timer_resume_at': False, 'date_end': now})
        return secs

    def _people(self):
        self.ensure_one()
        return self.employee_id | self.participant_ids

    def action_finish_report(self, qty_ok, qty_ng=0.0, qty_scrap=0.0, scrap_reason=False, at=None):
        """报工模式完工：累计工时随报工落库，按人生成工时记录。"""
        self.ensure_one()
        if self.manage_mode != 'report':
            raise UserError(_('过站模式请用「完工」直接按合格过站数结束计时。'))
        secs = self._stop(at)
        people = self._people()
        ratios = self.env['sn.wsd.piece.settlement']._distribute_ratios([1.0] * len(people))
        hours = round(secs / 3600.0, 4)
        window = {
            'start': self.date_start, 'end': self.date_end, 'seconds': secs,
            'source': 'terminal', 'alloc': 'duty',
            'hours_by_emp': {e.id: hours for e in people},
            'participants': [{'employee_id': e.id, 'performance_ratio': r, 'sequence': 10 * (i + 1)}
                             for i, (e, r) in enumerate(zip(people, ratios))],
        }
        report = self.mes_order_id.with_context(
            sn_timer_window=window, sn_timer_id=self.id).report_operation_qty(
            self.route_operation_id, qty_ok, qty_ng=qty_ng, qty_scrap=qty_scrap,
            scrap_reason=scrap_reason)
        self.write({'state': 'done', 'report_id': report.id if report else False,
                    'qty_ok': qty_ok})
        return report

    def action_finish_station(self, at=None):
        """过站模式完工：统计计时时段内本工序合格过站数，按人生成工时记录。"""
        self.ensure_one()
        if self.manage_mode != 'station':
            raise UserError(_('报工模式完工需要录入数量。'))
        secs = self._stop(at)
        self.env['sn.wsd.serial.operation.history'].flush_model()
        self.env.cr.execute("""
            SELECT COUNT(*) FROM sn_wsd_serial_operation_history
             WHERE mes_order_id = %s AND route_operation_id = %s AND result = 'ok'
               AND out_date >= %s AND out_date <= %s
        """, (self.mes_order_id.id, self.route_operation_id.id, self.date_start, self.date_end))
        qty = float(self.env.cr.fetchone()[0])
        people = self._people()
        hours = round(secs / 3600.0, 4)
        Entry = self.env['sn.wsd.time.entry']
        for emp in people:
            Entry.create({
                'company_id': self.company_id.id,
                'employee_id': emp.id,
                'category': 'production',
                'mes_order_id': self.mes_order_id.id,
                'route_operation_id': self.route_operation_id.id,
                'timer_id': self.id,
                'date_start': self.date_start,
                'date_end': self.date_end,
                'hours': hours,
                'qty_ok': round(qty / len(people), 2),
                'source': 'station',
                'state': 'confirmed',
            })
        self.write({'state': 'done', 'qty_ok': qty})
        return qty

    def action_cancel(self):
        for t in self:
            if t.state == 'done':
                raise UserError(_('已完工的计时不能取消。'))
        self.write({'state': 'cancelled', 'timer_resume_at': False})
        return True

    def timer_info(self):
        self.ensure_one()
        return {'id': self.id, 'name': self.name, 'state': self.state,
                'seconds': self._live_seconds(), 'order_id': self.mes_order_id.id,
                'people': ', '.join(self._people().mapped('name'))}

    # ------------------------------------------------------------------
    # 工位终端接口
    # ------------------------------------------------------------------
    @api.model
    def _terminal_employee(self):
        Emp = self.env['hr.employee']
        owner = Emp.sn_shop_floor_get_session_owner_id() if hasattr(
            Emp, 'sn_shop_floor_get_session_owner_id') else False
        employee = Emp.browse(owner) if owner else self.env.user.employee_id
        if not employee:
            raise UserError(_('终端未登录操作员，不能计时。'))
        connected = Emp.browse(Emp.sn_shop_floor_get_connected_ids()) if hasattr(
            Emp, 'sn_shop_floor_get_connected_ids') else Emp
        return employee, (connected - employee)

    @api.model
    def _terminal_active(self, order, route_operation, employee):
        return self.search([
            ('mes_order_id', '=', order.id), ('route_operation_id', '=', route_operation.id),
            ('employee_id', '=', employee.id), ('state', 'in', ('running', 'paused')),
        ], limit=1)

    @api.model
    def terminal_timer_action(self, order_id, workcenter_id, action):
        order = self.env['sn.wsd.mes.order'].browse(order_id)
        workcenter = self.env['mrp.workcenter'].browse(workcenter_id)
        route_operation = order._resolve_route_operation(workcenter)
        employee, others = self._terminal_employee()
        timer = self._terminal_active(order, route_operation, employee)
        if action == 'start':
            if timer:
                raise UserError(_('该工序已在计时。'))
            self.start(employee, order, route_operation, participants=others, workcenter=workcenter)
        elif action == 'pause':
            timer.action_pause()
        elif action == 'resume':
            timer.action_resume()
        elif action == 'finish':
            if not timer:
                raise UserError(_('没有进行中的计时。'))
            timer.action_finish_station()
        return order.sn_station_floor_data(workcenter_id)


class MesOrderStationTimer(models.Model):
    _inherit = 'sn.wsd.mes.order'

    def sn_station_floor_data(self, workcenter_id=False):
        data = super().sn_station_floor_data(workcenter_id)
        timers = {}
        Timer = self.env['sn.wsd.work.timer']
        try:
            employee, _others = Timer._terminal_employee()
        except UserError:
            employee = False
        if employee:
            for order in data.get('orders', []):
                op_id = (order.get('op') or {}).get('id')
                if not op_id:
                    continue
                timer = Timer.search([
                    ('mes_order_id', '=', order['id']), ('route_operation_id', '=', op_id),
                    ('employee_id', '=', employee.id), ('state', 'in', ('running', 'paused')),
                ], limit=1)
                if timer:
                    timers[str(order['id'])] = timer.timer_info()
        data['sn_timers'] = timers
        data['sn_require_hours'] = _require_hours(self.env)
        return data

    def sn_station_report(self, workcenter_id, qty_ok, qty_ng=0.0, qty_scrap=0.0,
                          scrap_reason_id=False):
        """终端报工：有进行中的计时 → 结束计时并把累计工时随报工落库。"""
        workcenter = self.env['mrp.workcenter'].browse(workcenter_id)
        route_operation = self._resolve_route_operation(workcenter)
        Timer = self.env['sn.wsd.work.timer']
        employee, _others = Timer._terminal_employee()
        timer = Timer._terminal_active(self, route_operation, employee)
        if timer:
            reason = self.env['sn.wsd.scrap.reason'].browse(
                int(scrap_reason_id) if scrap_reason_id else False)
            timer.action_finish_report(qty_ok, qty_ng, qty_scrap, scrap_reason=reason)
            return self.sn_station_floor_data(workcenter_id)
        if _require_hours(self.env) and (qty_ok or qty_scrap):
            raise UserError(_('请先点「开工」开始计时，完工报工时系统自动计算工时。'))
        return super().sn_station_report(workcenter_id, qty_ok, qty_ng, qty_scrap, scrap_reason_id)
