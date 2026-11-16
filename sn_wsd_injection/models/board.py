from datetime import timedelta

from odoo import api, fields, models

from .machine import RUN_STATES
from .shift import shift_of, shift_window


class SnInjBoardService(models.AbstractModel):
    """注塑车间机台看板数据源（client action 调用）。"""
    _name = 'sn.inj.board.service'
    _description = '注塑车间看板服务'

    @api.model
    def get_board_data(self):
        now = fields.Datetime.now()
        day, shift = shift_of(self.env, now)
        s_start, _s_end = shift_window(self.env, day, shift)
        Report = self.env['sn.inj.report']
        Shot = self.env['sn.inj.shot']
        machines = self.env['sn.inj.machine'].search([])
        state_labels = dict(RUN_STATES)
        rows = []
        for m in machines:
            plan = m.current_plan_id
            next_plan = False
            if not plan:
                plan = self.env['sn.inj.plan'].search([('machine_id', '=', m.id), ('state', '=', 'confirmed')],
                                                      order='date_start', limit=1)
                next_plan = bool(plan)
            mold = m.current_mold_id
            shots30 = Shot.search([('machine_id', '=', m.id)], order='shot_time desc', limit=30)
            shots = shots30[:20]
            last_cycle = sum(shots.mapped('cycle_time')) / len(shots) if shots else 0.0
            last_rep = Report.search([('machine_id', '=', m.id), ('state', '=', 'done')], order='report_time desc', limit=1)
            today_good = sum(Report.search([('machine_id', '=', m.id), ('state', '=', 'done'), ('date', '=', day),
                                            ('shift', '=', shift)]).mapped('good_qty'))
            std = (mold.std_cycle if next_plan else plan.std_cycle) or mold.std_cycle or 0.0
            dev = (last_cycle - std) / std * 100.0 if std and last_cycle else 0.0
            reps = Report.search([('machine_id', '=', m.id), ('state', '=', 'done'),
                                  ('report_time', '>=', now - timedelta(hours=24))])
            planned = sum(reps.mapped('planned_minutes'))
            oee = sum(r.oee * r.planned_minutes for r in reps) / planned if planned else 0.0
            out_24h = Shot.search_count([('machine_id', '=', m.id), ('is_out', '=', True),
                                         ('shot_time', '>=', now - timedelta(hours=24))])
            mins = int((now - m.state_since).total_seconds() // 60) if m.state_since else 0
            rows.append({
                'id': m.id, 'code': m.code, 'name': m.name, 'tonnage': m.tonnage,
                'brand': dict(m._fields['brand'].selection).get(m.brand, ''),
                'state': m.run_state, 'state_label': state_labels.get(m.run_state, ''),
                'state_minutes': mins, 'state_note': m.state_note or '',
                'mold': mold.sn or '', 'mold_name': mold.name or '',
                'cavity': mold.cavity_text or '',
                'mold_warn': mold.warn_level or 'normal', 'mold_warn_text': mold.warn_text or '',
                'maint_pct': round(mold.maint_progress or 0, 1), 'life_pct': round(mold.life_progress or 0, 1),
                'product': plan.product_id.name or (mold.product_names or ''),
                'plan': plan.name or '', 'plan_qty': plan.planned_qty or 0, 'good': plan.good_qty or 0,
                'next_plan': next_plan, 'operator': last_rep.operator_id.name or '', 'shift_good': int(today_good),
                'spark': [round(c, 2) for c in reversed(shots30.mapped('cycle_time'))],
                'spark_out': [bool(o) for o in reversed(shots30.mapped('is_out'))],
                'progress': round(plan.progress or 0, 1),
                'std_cycle': round(std, 1), 'cycle': round(last_cycle, 1), 'cycle_dev': round(dev, 1),
                'oee': round(oee, 1), 'out_24h': out_24h,
            })
        shift_reports = Report.search([('state', '=', 'done'), ('report_time', '>=', now - timedelta(hours=24))])
        total = sum(shift_reports.mapped('total_qty'))
        good = sum(shift_reports.mapped('good_qty'))
        planned = sum(shift_reports.mapped('planned_minutes'))
        oee_all = sum(r.oee * r.planned_minutes for r in shift_reports) / planned if planned else 0.0
        changes = self.env['sn.inj.mold.change'].search_count([('actual_start', '>=', now - timedelta(days=7))])
        avg_change = self.env['sn.inj.mold.change'].search([('state', '=', 'done'),
                                                           ('actual_start', '>=', now - timedelta(days=30))])
        defect_rows = self.env['sn.inj.report.defect']._read_group(
            [('report_id.report_time', '>=', now - timedelta(days=7))], ['defect_id'], ['qty:sum'])
        defects = sorted([{'name': d.name, 'qty': q} for d, q in defect_rows], key=lambda r: -r['qty'])[:6]
        alerts = []
        for t in self.env['sn.wsd.exception.ticket'].search([('state', 'not in', ('done', 'cancelled')),
                                                             ('workshop_id.code', '=', 'WS-INJ')],
                                                            order='reported_at desc', limit=4):
            alerts.append({'level': 'red', 'text': (t.description or '').replace('【工艺参数超限】', '参数超限 · ')[:80],
                           'time': fields.Datetime.context_timestamp(self, t.reported_at).strftime('%m-%d %H:%M')})
        for mold in self.env['sn.inj.mold'].search([('warn_level', '!=', 'normal')], limit=4):
            alerts.append({'level': 'amber' if mold.warn_level == 'warn' else 'red',
                           'text': '模具 %s %s：%s（保养 %s%%，寿命 %s%%）' % (
                               mold.sn, mold.name, mold.warn_text, round(mold.maint_progress), round(mold.life_progress)),
                           'time': ''})
        for d in self.env['sn.inj.drying'].search([('state', 'in', ('expired', 'ng'))], limit=3):
            alerts.append({'level': 'amber', 'text': '烘干 %s %s %s：%s' % (
                d.name, d.grade_id.name, d.lot_no, dict(d._fields['state'].selection).get(d.state)), 'time': ''})
        counts = {}
        for r in rows:
            counts[r['state']] = counts.get(r['state'], 0) + 1
        return {
            'now': fields.Datetime.context_timestamp(self, now).strftime('%Y-%m-%d %H:%M'),
            'shift': '%s %s' % (day.strftime('%m-%d'), '白班' if shift == 'day' else '夜班'),
            'machines': rows,
            'summary': {
                'machines': len(rows), 'running': counts.get('running', 0),
                'stopped': len(rows) - counts.get('running', 0),
                'total': total, 'good': good, 'yield': round(good * 100.0 / total, 2) if total else 0,
                'oee': round(oee_all, 1), 'changes_7d': changes,
                'avg_change': round(sum(avg_change.mapped('duration_minutes')) / len(avg_change), 0) if avg_change else 0,
                'mold_warn': self.env['sn.inj.mold'].search_count([('warn_level', '!=', 'normal')]),
                'out_24h': Shot.search_count([('is_out', '=', True), ('shot_time', '>=', now - timedelta(hours=24))]),
            },
            'states': [{'key': k, 'label': v, 'count': counts.get(k, 0)} for k, v in RUN_STATES],
            'defects': defects,
            'alerts': alerts[:8],
        }
