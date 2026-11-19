from odoo import api, fields, models, _

from .demo_data import get_mes_demo_data


class SnWsdMesDashboardService(models.AbstractModel):
    _name = 'sn.wsd.mes.dashboard.service'
    _description = 'MES Dashboard Service'

    @api.model
    def _progress_row(self, order):
        """按最新 MES 制令单字段汇总单张工单的进度。

        produced_qty / x_progress_rate / x_yield_total 分别是最新代码里
        产出、完成进度、良率的权威口径；不良与报废取工序上的 x_ng_qty、
        x_scrap_qty，不再在大屏里写死 0 和 100%。
        """
        ops = order.x_route_operation_ids
        return {
            'production_name': order.name,
            'product_qty': order.planned_qty,
            'qty_output_total': order.produced_qty,
            'qty_pass': order.produced_qty,
            'qty_fail': sum(ops.mapped('x_ng_qty') or []),
            'qty_scrap': sum(ops.mapped('x_scrap_qty') or []),
            'progress_rate': round(order.x_progress_rate or 0.0, 2),
            'pass_rate': round((order.x_yield_total or 0.0) * 100.0, 2),
            'progress_status': 'normal' if order.state == 'done' else 'warning',
        }

    @api.model
    def get_big_screen_data(self):
        # 无 MES 工单数据时启用集中管理的占位演示数据（见 demo_data.py），
        # 存在真实数据后自动切回真实查询。
        if not self.env['sn.wsd.mes.order'].search_count([]):
            data = get_mes_demo_data()
            data['summary']['is_demo'] = True
            return data
        today = fields.Date.context_today(self)
        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        mes_orders = self.env['sn.wsd.mes.order'].search([], order='id desc', limit=8)
        # 过站窗口只取已完成行（pass-history-on-enter）：在制行 out_date
        # 为空且排序置顶，不排除会把固定窗口挤满、今日统计被稀释
        histories = self.env['sn.wsd.serial.operation.history'].search(
            [('result', '!=', 'in_progress')],
            order='out_date desc, id desc', limit=48)
        tests = self.env['sn.wsd.mes.test.result'].search([], order='test_time desc, id desc', limit=24)

        today_histories = histories.filtered(
            lambda rec: rec.out_date and rec.out_date.date() == today)
        # test_time is stored in UTC: compare its local date with context_today()
        # so tests done between 00:00 and 08:00 local time stay in today
        today_tests = tests.filtered(
            lambda rec: rec.test_time
            and fields.Datetime.context_timestamp(self, rec.test_time).date() == today)
        station_rows = {}
        for history in today_histories:
            station_code = history.workcenter_id.code or '-'
            row = station_rows.setdefault(station_code, {
                'station_code': station_code,
                'qty_in': 0.0,
                'qty_out': 0.0,
                'qty_ng': 0.0,
                'qty_scrap': 0.0,
            })
            row['qty_in'] += 1.0
            row['qty_out'] += 1.0
            if history.result == 'ng':
                row['qty_ng'] += 1.0
            elif history.result == 'scrap':
                row['qty_scrap'] += 1.0

        congestion_rows = []
        abnormal_rows = []
        for row in station_rows.values():
            row['backlog_qty'] = max(row['qty_in'] - row['qty_out'], 0.0)
            row['pass_rate'] = round((row['qty_out'] - row['qty_ng'] - row['qty_scrap']) / row['qty_out'] * 100.0, 2) if row['qty_out'] else 0.0
            row['efficiency_rate'] = row['pass_rate']
            row['avg_cycle_time_sec'] = 0.0
            row['alert_level'] = (
                'danger' if row['backlog_qty'] >= 20 or row['pass_rate'] < 70.0
                else 'warning' if row['backlog_qty'] >= 5 or row['pass_rate'] < 85.0
                else 'normal'
            )
            abnormal_qty = row['qty_ng'] + row['qty_scrap']
            abnormal_rows.append({
                'station_code': row['station_code'],
                'qty_ng': row['qty_ng'],
                'qty_scrap': row['qty_scrap'],
                'abnormal_qty': abnormal_qty,
                'abnormal_rate': round(abnormal_qty / row['qty_out'] * 100.0, 2) if row['qty_out'] else 0.0,
                'qty_out': row['qty_out'],
            })
            congestion_rows.append(row)

        abnormal_rows.sort(key=lambda item: (item['abnormal_qty'], item['abnormal_rate']), reverse=True)
        congestion_rows.sort(key=lambda item: (item['backlog_qty'], -item['efficiency_rate']), reverse=True)
        open_alert_count = len([row for row in congestion_rows if row['alert_level'] != 'normal'])

        return {
            'summary': {
                'production_count': self.env['sn.wsd.mes.order'].search_count([]),
                'open_progress_count': len(mes_orders.filtered(lambda order: order.state not in ('done', 'cancelled'))),
                'today_output_total': len(today_histories.filtered(lambda h: h.result == 'ok')),
                'today_pass_total': len(today_tests.filtered(lambda test: test.result == 'ok')),
                'today_test_count': len(today_tests),
                'today_date': fields.Date.to_string(today),
                'refresh_time': now.strftime('%Y-%m-%d %H:%M:%S'),
                'station_alert_count': open_alert_count,
            },
            'production_progress': [
                self._progress_row(order) for order in mes_orders
            ],
            'operation_daily': [],
            'test_pass_rates': [],
            'aging_losses': [],
            'repair_closures': [],
            'station_efficiency': [],
            'test_history': [
                {
                    'test_time': rec.test_time,
                    'serial_no': rec.serial_identity_id.name,
                    'test_type': rec.test_type,
                    'result': rec.result,
                    'station_code': rec.workcenter_code,
                    'operator_code': rec.operator_code,
                    'cycle_time_sec': rec.cycle_time_sec,
                    'status': 'danger' if rec.result == 'ng' else 'warning' if rec.result == 'hold' else 'normal',
                }
                for rec in tests[:12]
            ],
            'serial_trace': [
                {
                    'event_time': rec.out_date,
                    'serial_no': rec.serial_identity_id.name,
                    'event_source': 'station',
                    'event_type': rec.result,
                    'station_code': rec.workcenter_id.code or '-',
                    'result': rec.result,
                    'quantity': 1.0,
                    'reference_name': rec.route_operation_id.display_name or '-',
                    'status': 'danger' if rec.result in ('ng', 'scrap') else 'normal',
                }
                for rec in histories[:12]
            ],
            'top_abnormal_stations': abnormal_rows[:6],
            'station_congestion': congestion_rows[:6],
        }

    @api.model
    def action_open_big_screen(self):
        client_action = self.env.ref(
            'sn_wsd_report.action_sn_wsd_mes_big_screen_client',
            raise_if_not_found=False,
        )
        if client_action:
            action = client_action.read()[0]
            action['name'] = _('MES Big Screen')
            return action
        return {
            'type': 'ir.actions.client',
            'tag': 'sn_wsd_mes_big_screen_action',
            'name': _('MES Big Screen'),
            'target': 'fullscreen',
            'path': 'sn-wsd-mes-big-screen-display',
            'context': {},
        }
