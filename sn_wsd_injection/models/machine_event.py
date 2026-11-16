from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .machine import RUN_STATES
from .shift import SHIFTS, shift_of, shift_window

# 机台状态 → 现有 OEE 模型的停机原因
DOWNTIME_MAP = {
    'fault': 'breakdown',
    'changeover': 'changeover',
    'wait_material': 'material',
    'idle': 'other',
}


class SnInjMachineEvent(models.Model):
    """机台状态/计数事件：数采网关经 /api/injection/status 上报（状态切换 + 模次计数器）。
    按班次汇总生成 OEE 记录写入设备模块现有的 OEE 模型（sn.wsd.device.oee.record）。"""
    _name = 'sn.inj.machine.event'
    _description = '注塑机状态事件'
    _order = 'event_time desc, id desc'

    machine_id = fields.Many2one('sn.inj.machine', string='机台', required=True, index=True)
    event_time = fields.Datetime(string='时间', required=True, default=fields.Datetime.now, index=True)
    shift_date = fields.Date(string='班次日期', compute='_compute_shift', store=True, index=True)
    shift = fields.Selection(SHIFTS, string='班次', compute='_compute_shift', store=True)
    state = fields.Selection(RUN_STATES, string='状态', required=True)
    counter = fields.Integer(string='模次计数器', aggregator=None)
    mold_id = fields.Many2one('sn.inj.mold', string='模具')
    alarm = fields.Char(string='报警/说明')
    source = fields.Selection([('api', '数采网关'), ('manual', '手工')], string='来源', default='api')

    @api.depends('event_time')
    def _compute_shift(self):
        for ev in self:
            if ev.event_time:
                ev.shift_date, ev.shift = shift_of(self.env, ev.event_time)
            else:
                ev.shift_date, ev.shift = False, False

    @api.model_create_multi
    def create(self, vals_list):
        events = super().create(vals_list)
        if not self.env.context.get('inj_no_state_sync'):
            for ev in events:
                m = ev.machine_id
                if not m.state_since or ev.event_time >= m.state_since:
                    m.write({'run_state': ev.state, 'state_since': ev.event_time, 'state_note': ev.alarm or False})
        return events

    @api.model
    def api_status(self, payload):
        rows = payload.get('events') if isinstance(payload.get('events'), list) else [payload]
        vals_list = []
        for row in rows:
            machine = self.env['sn.inj.machine'].search([('code', '=', row.get('machine'))], limit=1)
            if not machine:
                raise UserError(_('机台 %s 不存在。', row.get('machine')))
            if row.get('state') not in dict(RUN_STATES):
                raise UserError(_('状态 %s 无效，可选：%s', row.get('state'), ', '.join(dict(RUN_STATES))))
            vals = {'machine_id': machine.id, 'state': row['state'], 'counter': int(row.get('counter') or 0),
                    'mold_id': machine.current_mold_id.id, 'alarm': row.get('alarm') or False, 'source': 'api'}
            if row.get('time'):
                vals['event_time'] = fields.Datetime.to_datetime(row['time'])
            vals_list.append(vals)
        events = self.create(vals_list)
        return [{'id': e.id, 'machine': e.machine_id.code, 'state': e.state, 'shift': e.shift,
                 'shift_date': fields.Date.to_string(e.shift_date)} for e in events]


class SnInjMachineOee(models.Model):
    _inherit = 'sn.inj.machine'

    def _shift_summary(self, day, shift):
        """一个机台一个班次：各状态时长（小时）、班内模次（计数器差）、良品/总数（报工）。"""
        self.ensure_one()
        start, end = shift_window(self.env, day, shift)
        Event = self.env['sn.inj.machine.event']
        before = Event.search([('machine_id', '=', self.id), ('event_time', '<', start)],
                              order='event_time desc, id desc', limit=1)
        inside = Event.search([('machine_id', '=', self.id), ('event_time', '>=', start),
                               ('event_time', '<', end)], order='event_time, id')
        if not before and not inside:
            return False
        durations = {}
        cur_state = before.state if before else inside[0].state
        cur_time = start
        counters = [before.counter] if before and before.counter else []
        for ev in inside:
            durations[cur_state] = durations.get(cur_state, 0.0) + (ev.event_time - cur_time).total_seconds()
            cur_state, cur_time = ev.state, ev.event_time
            if ev.counter:
                counters.append(ev.counter)
        cap_end = min(end, fields.Datetime.now()) if end > fields.Datetime.now() else end
        durations[cur_state] = durations.get(cur_state, 0.0) + max((cap_end - cur_time).total_seconds(), 0)
        hours = {k: v / 3600.0 for k, v in durations.items()}
        shots = (max(counters) - min(counters)) if len(counters) >= 2 else 0
        reports = self.env['sn.inj.report'].search([('machine_id', '=', self.id), ('date', '=', day),
                                                     ('shift', '=', shift), ('state', '=', 'done')])
        mold = (inside[-1:] or before).mold_id or self.current_mold_id
        cavity = sum(mold._cavity_for(pl.product_id, start) for pl in mold.product_line_ids) if mold else 1
        total = sum(reports.mapped('total_qty')) or shots * cavity
        good = sum(reports.mapped('good_qty')) if reports else total
        std = (reports[:1].std_cycle or mold.std_cycle) if mold else 0
        return {'start': start, 'end': cap_end, 'hours': hours, 'shots': shots, 'cavity': cavity,
                'total': total, 'good': min(good, total), 'std_cycle': std}

    def action_generate_oee(self, day=None, shift=None):
        """按机台按班生成/刷新 OEE 记录（写入现有 OEE 模型）。"""
        Oee = self.env['sn.wsd.device.oee.record']
        if not day:
            day, shift = shift_of(self.env, fields.Datetime.now() - timedelta(hours=12))
        records = Oee.browse()
        for machine in self:
            data = machine._shift_summary(day, shift)
            if not data or not data['std_cycle']:
                continue
            hours = data['hours']
            planned = round(((data['end'] - data['start']).total_seconds() / 3600.0) - hours.get('planned_stop', 0.0), 2)
            if planned <= 0:
                continue
            downtime = [(0, 0, {'reason': DOWNTIME_MAP[k], 'hours': round(v, 2),
                                'remark': dict(RUN_STATES)[k]})
                        for k, v in hours.items() if k in DOWNTIME_MAP and v >= 0.01]
            vals = {
                'equipment_id': machine.equipment_id.id, 'date': day, 'shift': shift,
                'planned_time': planned,
                'design_capacity': round(3600.0 / data['std_cycle'] * data['cavity'], 1),
                'actual_output': int(data['total']), 'qualified_qty': int(data['good']),
                'note': _('注塑数采自动汇总：模次 %(s)s，穴数 %(c)s', s=data['shots'], c=data['cavity']),
            }
            rec = Oee.search([('equipment_id', '=', machine.equipment_id.id), ('date', '=', day),
                              ('shift', '=', shift)], limit=1)
            if rec:
                rec.downtime_ids.unlink()
                rec.write(dict(vals, downtime_ids=downtime, state='draft'))
            else:
                rec = Oee.create(dict(vals, downtime_ids=downtime))
            if sum(l[2]['hours'] for l in downtime) > planned:
                rec.downtime_ids[-1:].hours = max(planned - sum(rec.downtime_ids[:-1].mapped('hours')), 0)
            if rec.actual_output > 0:
                rec.state = 'done'
            records |= rec
        return records

    @api.model
    def _cron_generate_oee(self):
        day, shift = shift_of(self.env, fields.Datetime.now() - timedelta(hours=12))
        return self.search([]).action_generate_oee(day, shift)
