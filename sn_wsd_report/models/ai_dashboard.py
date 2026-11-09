import datetime

from odoo import api, fields, models, _

from .demo_data import get_ai_demo_data

DIMENSIONS = ('workorder', 'team', 'equipment')


class SnWsdAiDashboardService(models.AbstractModel):
    _name = 'sn.wsd.ai.dashboard.service'
    _description = 'Multi-Dimension Dashboard Service'

    @api.model
    def _real_workorder_data(self, today_start_str, today):
        orders = self.env['sn.wsd.mes.order'].search([], order='id desc', limit=12)
        rows = []
        comparison_labels = []
        comparison_planned = []
        comparison_actual = []
        worktime_labels = []
        worktime_values = []
        for order in orders:
            name = order.name or '-'
            planned = order.planned_qty or 0.0
            # produced_qty 是最新代码里 MES 制令单的产出聚合字段
            actual = order.produced_qty or 0.0
            rate = round(actual / planned * 100.0, 1) if planned else 0.0
            state_label = '完成' if order.state == 'done' else '进行中' if order.state != 'cancelled' else '已取消'
            level = 'ok' if order.state == 'done' else 'normal'
            if order.state != 'done' and rate < 70:
                level = 'warning'
            rows.append({
                'cells': [name, order.product_id.display_name or '-',
                          f'{planned:g}', f'{actual:g}', f'{rate}%', state_label],
                'level': level,
            })
            if len(comparison_labels) < 6:
                comparison_labels.append(name[:10])
                comparison_planned.append(planned)
                comparison_actual.append(actual)
                worktime_labels.append(name[:10])
                worktime_values.append(round(actual * 0.17, 1))
        total_output = sum(o.produced_qty or 0.0 for o in orders)
        total_planned = sum(o.planned_qty or 0.0 for o in orders)
        total_hours = round(total_output * 0.17, 1)
        return {
            'dimension_label': '工单',
            'kpi': [
                {'label': '工单总数', 'value': len(orders), 'suffix': '', 'digits': 0, 'color': 'cyan'},
                {'label': '总产量', 'value': round(total_output), 'suffix': ' 件', 'digits': 0, 'color': 'cyan'},
                {'label': '总工时', 'value': total_hours, 'suffix': ' h', 'digits': 0, 'color': 'green'},
                {'label': '目标达成率',
                 'value': round(total_output / total_planned * 100.0, 1) if total_planned else 0.0,
                 'suffix': '%', 'digits': 1, 'color': 'amber'},
                {'label': '进行中工单', 'value': len([o for o in orders if o.state not in ('done', 'cancelled')]),
                 'suffix': '', 'digits': 0, 'color': 'purple'},
                {'label': '异常工单', 'value': 0, 'suffix': '', 'digits': 0, 'color': 'red'},
            ],
            'comparison': {
                'labels': comparison_labels,
                'planned': comparison_planned,
                'actual': comparison_actual,
            },
            'detail': {
                'columns': ['工单号', '产品', '计划', '实际', '进度', '状态'],
                'rows': rows,
            },
            'worktime_dist': {'labels': worktime_labels, 'values': worktime_values},
        }

    @api.model
    def _real_equipment_data(self, today):
        equipments = self.env['sn.wsd.device.equipment'].search([], limit=12)
        if not equipments:
            # 未维护设备档案时退化为按工作中心展示，避免设备维度整屏空白
            return self._workcenter_equipment_data()
        rows = []
        comparison_labels = []
        comparison_planned = []
        comparison_actual = []
        worktime_labels = []
        worktime_values = []
        status_label_map = {'enabled': '运行', 'repair': '维修', 'sealed': '封存', 'scrapped': '报废'}
        status_level_map = {'enabled': 'ok', 'repair': 'danger', 'sealed': 'idle', 'scrapped': 'idle'}
        oee_sum = 0.0
        oee_count = 0
        machine_hours = 0.0
        for eq in equipments:
            latest_oee = self.env['sn.wsd.device.oee.record'].search(
                [('equipment_id', '=', eq.id), ('date', '=', today)],
                order='id desc', limit=1,
            )
            oee = round(latest_oee.oee_value, 1) if latest_oee else 0.0
            run_hours = latest_oee.run_hours if latest_oee else 0.0
            output = round((latest_oee.theoretical_output or 0.0) * (oee / 100.0)) if latest_oee else 0
            if latest_oee and latest_oee.oee_value:
                oee_sum += latest_oee.oee_value
                oee_count += 1
            machine_hours += run_hours
            label = status_label_map.get(eq.equipment_status, eq.equipment_status or '-')
            level = status_level_map.get(eq.equipment_status, 'idle')
            rows.append({
                'cells': [eq.code or '-', eq.name or '-', label,
                          f'{output}', f'{run_hours:g} h', f'{oee}%'],
                'level': level,
            })
            if len(comparison_labels) < 6:
                comparison_labels.append((eq.code or '-')[:10])
                comparison_planned.append(round(latest_oee.theoretical_output or 0.0) if latest_oee else 0)
                comparison_actual.append(output)
                worktime_labels.append((eq.code or '-')[:10])
                worktime_values.append(round(run_hours, 1))
        avg_oee = round(oee_sum / oee_count, 1) if oee_count else 0.0
        running = len([e for e in equipments if e.equipment_status == 'enabled'])
        return {
            'dimension_label': '设备',
            'kpi': [
                {'label': '设备总数', 'value': len(equipments), 'suffix': '', 'digits': 0, 'color': 'cyan'},
                {'label': '运行中', 'value': running, 'suffix': ' 台', 'digits': 0, 'color': 'green'},
                {'label': '总机时', 'value': round(machine_hours), 'suffix': ' h', 'digits': 0, 'color': 'amber'},
                {'label': '平均稼动率', 'value': avg_oee, 'suffix': '%', 'digits': 1, 'color': 'purple'},
                {'label': '故障/维修', 'value': len([e for e in equipments if e.equipment_status == 'repair']),
                 'suffix': ' 台', 'digits': 0, 'color': 'red'},
                {'label': '今日盘点', 'value': 0, 'suffix': '', 'digits': 0, 'color': 'cyan'},
            ],
            'comparison': {
                'labels': comparison_labels,
                'planned': comparison_planned,
                'actual': comparison_actual,
            },
            'detail': {
                'columns': ['编码', '名称', '状态', '产量', '机时', 'OEE'],
                'rows': rows,
            },
            'worktime_dist': {'labels': worktime_labels, 'values': worktime_values},
        }

    @api.model
    def _workcenter_equipment_data(self):
        """设备档案为空时的降级视图：按工作中心统计过站通过与不良数。"""
        workcenters = self.env['mrp.workcenter'].search([], limit=12)
        History = self.env['sn.wsd.serial.operation.history']
        rows = []
        comparison_labels = []
        comparison_actual = []
        worktime_labels = []
        worktime_values = []
        total_ok = 0
        for workcenter in workcenters:
            ok_qty = History.search_count([
                ('workcenter_id', '=', workcenter.id), ('result', '=', 'ok')])
            ng_qty = History.search_count([
                ('workcenter_id', '=', workcenter.id),
                ('result', 'in', ('ng', 'scrap'))])
            total = ok_qty + ng_qty
            rate = round(ok_qty / total * 100.0, 1) if total else 0.0
            rows.append({
                'cells': [workcenter.code or '-', workcenter.name or '-', '运行',
                          '%d' % ok_qty, '%d' % ng_qty, '%.1f%%' % rate],
                'level': 'warning' if ng_qty else 'ok',
            })
            if len(comparison_labels) < 6:
                comparison_labels.append((workcenter.code or '-')[:10])
                comparison_actual.append(ok_qty)
                worktime_labels.append((workcenter.code or '-')[:10])
                worktime_values.append(ng_qty)
            total_ok += ok_qty
        return {
            'dimension_label': '设备',
            'kpi': [
                {'label': '工作中心', 'value': len(workcenters), 'suffix': ' 个', 'digits': 0, 'color': 'cyan'},
                {'label': '运行中', 'value': len(workcenters), 'suffix': ' 个', 'digits': 0, 'color': 'green'},
                {'label': '累计通过', 'value': total_ok, 'suffix': ' 人次', 'digits': 0, 'color': 'cyan'},
                {'label': '平均稼动率', 'value': 0.0, 'suffix': '%', 'digits': 1, 'color': 'purple'},
                {'label': '故障/维修', 'value': 0, 'suffix': ' 个', 'digits': 0, 'color': 'red'},
                {'label': '今日盘点', 'value': 0, 'suffix': '', 'digits': 0, 'color': 'cyan'},
            ],
            'comparison': {
                'labels': comparison_labels,
                'planned': [round(value * 1.05) for value in comparison_actual],
                'actual': comparison_actual,
            },
            'detail': {
                'columns': ['编码', '名称', '状态', '通过', '不良', '直通率'],
                'rows': rows,
            },
            'worktime_dist': {'labels': worktime_labels, 'values': worktime_values},
        }

    @api.model
    def _real_team_data(self, today_start_str):
        """按操作员聚合为班组视角（每名操作员代表一个作业组）。

        数据源用 sn.wsd.serial.operation.history：上游做 SN 统一时删除了
        sn.wsd.mes.sn.travel，过站记录统一收敛到该模型。
        """
        histories = self.env['sn.wsd.serial.operation.history'].search([
            ('out_date', '>=', today_start_str),
            ('result', 'in', ('ok', 'ng')),
        ])
        if not histories:
            # 今日尚无过站记录时回退最近 7 天，避免班组维度整屏空白
            week_ago = fields.Datetime.to_string(
                fields.Datetime.now() - datetime.timedelta(days=7))
            histories = self.env['sn.wsd.serial.operation.history'].search([
                ('out_date', '>=', week_ago),
                ('result', 'in', ('ok', 'ng')),
            ])
        by_operator = {}
        for history in histories:
            key = history.operator_code or '未分配'
            by_operator.setdefault(key, 0)
            by_operator[key] += 1
        rows = []
        comparison_labels = []
        comparison_actual = []
        worktime_labels = []
        worktime_values = []
        total_output = 0
        for operator, qty in sorted(by_operator.items(), key=lambda x: -x[1])[:6]:
            hours = round(qty * 0.19, 1)
            eff = round(qty / hours, 1) if hours else 0.0
            rows.append({
                'cells': [f'{operator} 作业组', operator, '-', f'{qty}', f'{hours:g} h', f'{eff} 件/h'],
                'level': 'normal',
            })
            comparison_labels.append(operator)
            comparison_actual.append(qty)
            worktime_labels.append(operator)
            worktime_values.append(hours)
            total_output += qty
        total_hours = round(total_output * 0.19, 1)
        return {
            'dimension_label': '班组',
            'kpi': [
                {'label': '作业组数', 'value': len(by_operator), 'suffix': '', 'digits': 0, 'color': 'cyan'},
                {'label': '总产量', 'value': total_output, 'suffix': ' 件', 'digits': 0, 'color': 'cyan'},
                {'label': '总工时', 'value': total_hours, 'suffix': ' h', 'digits': 0, 'color': 'green'},
                {'label': '人均效率', 'value': round(total_output / total_hours, 1) if total_hours else 0.0,
                 'suffix': ' 件/h', 'digits': 1, 'color': 'green'},
                {'label': '平均设备效率', 'value': 0.0, 'suffix': '%', 'digits': 1, 'color': 'purple'},
                {'label': '目标达成率', 'value': 0.0, 'suffix': '%', 'digits': 1, 'color': 'amber'},
            ],
            'comparison': {
                'labels': comparison_labels,
                'planned': [round(a * 1.1) for a in comparison_actual],
                'actual': comparison_actual,
            },
            'detail': {
                'columns': ['班组', '负责人', '人数', '产量', '工时', '效率'],
                'rows': rows,
            },
            'worktime_dist': {'labels': worktime_labels, 'values': worktime_values},
        }

    @api.model
    def get_ai_screen_data(self, dimension=None):
        dim = dimension if dimension in DIMENSIONS else 'workorder'
        # 无 MES 业务数据时启用集中管理的占位演示数据（见 demo_data.py），
        # 存在真实数据后自动切回真实聚合。
        if not self.env['sn.wsd.mes.order'].search_count([]):
            return get_ai_demo_data(dim)

        today = fields.Date.context_today(self)
        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        local_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = fields.Datetime.now() - (now - local_midnight)
        today_start_str = fields.Datetime.to_string(today_start_utc)

        if dim == 'equipment':
            dim_data = self._real_equipment_data(today)
        elif dim == 'team':
            dim_data = self._real_team_data(today_start_str)
        else:
            dim_data = self._real_workorder_data(today_start_str, today)

        # 趋势：近 12 小时出站（过站记录统一取 serial.operation.history）
        histories = self.env['sn.wsd.serial.operation.history'].search([
            ('out_date', '>=', today_start_str),
            ('result', 'in', ('ok', 'ng', 'scrap')),
        ])
        buckets = {}
        for h in range(12):
            buckets[(now.hour - 11 + h) % 24] = 0
        for history in histories:
            if history.out_date:
                local_dt = fields.Datetime.context_timestamp(self, history.out_date)
                if local_dt.hour in buckets:
                    buckets[local_dt.hour] += 1
        trend_labels = []
        trend_output = []
        trend_pass = []
        for h in range(12):
            hour = (now.hour - 11 + h) % 24
            trend_labels.append(f'{hour:02d}:00')
            trend_output.append(buckets[hour])
            trend_pass.append(0.0)

        # 实时动态：最近的异常过站
        fails = self.env['sn.wsd.serial.operation.history'].search([
            ('out_date', '>=', today_start_str),
            ('result', 'in', ('ng', 'scrap')),
        ], order='out_date desc', limit=8)
        result_label = {'ng': '不良', 'scrap': '报废'}
        live = [
            {
                'time': fields.Datetime.context_timestamp(
                    self, f.out_date).strftime('%H:%M') if f.out_date else '',
                'type': 'quality',
                'level': 'danger' if f.result == 'ng' else 'warning',
                'message': '%s %s SN:%s' % (
                    f.workcenter_id.code or '-',
                    result_label.get(f.result, f.result),
                    f.serial_identity_id.name or '-'),
                'ref': f.mes_order_id.name or '-',
            }
            for f in fails
        ]

        return {
            'dimension': dim,
            'dimension_label': dim_data['dimension_label'],
            'summary': {
                'today_output': len(histories),
                'oee': 0.0,
                'achieve_rate': 0.0,
                'total_hours': 0.0,
                'machine_hours': 0.0,
                'alerts': len(live),
                'today_date': fields.Date.to_string(today),
                'refresh_time': now.strftime('%Y-%m-%d %H:%M:%S'),
            },
            'kpi': dim_data['kpi'],
            'comparison': dim_data['comparison'],
            'detail': dim_data['detail'],
            'worktime_dist': dim_data['worktime_dist'],
            'hourly_trend': {
                'labels': trend_labels,
                'output': trend_output,
                'pass_rate': trend_pass,
            },
            'live_activities': live,
        }

    @api.model
    def action_open_ai_screen(self):
        client_action = self.env.ref(
            'sn_wsd_report.action_sn_wsd_ai_screen_client',
            raise_if_not_found=False,
        )
        if client_action:
            action = client_action.read()[0]
            action['name'] = _('Multi-Dimension Board')
            return action
        return {
            'type': 'ir.actions.client',
            'tag': 'sn_wsd_ai_screen_action',
            'name': _('Multi-Dimension Board'),
            'target': 'fullscreen',
            'context': {},
        }
