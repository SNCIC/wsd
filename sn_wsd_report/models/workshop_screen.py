import datetime

import pytz

from odoo import api, fields, models, _

HISTORY_MODEL = 'sn.wsd.serial.operation.history'

STATE_LABELS = {
    'draft': '草稿',
    'confirmed': '已确认',
    'in_progress': '生产中',
    'done': '已完工',
    'cancelled': '已取消',
}

RESULT_LABELS = {
    'ok': '通过',
    'ng': '不良',
    'scrap': '报废',
    'in_progress': '在制',
}

INSPECTION_TYPE_LABELS = {
    'fai': '首件检验',
    'iqc': '来料检验',
    'ipqc': '过程检验',
    'oqc': '出货检验',
}

INSPECTION_RESULT_LABELS = {
    'pending': '待判定',
    'pass': '合格',
    'partial': '部分合格',
    'fail': '不合格',
    'concession': '让步接收',
    'reject': '拒收',
}


def _local_day_bounds(env, day):
    """把某个本地日期换算成 UTC 的 [起, 止) 时间区间（naive datetime）。

    `out_date` 落库是 UTC，报表按用户时区的自然日统计才不会把凌晨
    8 点前的过站算到前一天。
    """
    tz_name = env.context.get('tz') or env.user.tz or 'UTC'
    tz = pytz.timezone(tz_name)
    start_local = tz.localize(datetime.datetime.combine(day, datetime.time.min))
    end_local = start_local + datetime.timedelta(days=1)
    return (
        start_local.astimezone(pytz.utc).replace(tzinfo=None),
        end_local.astimezone(pytz.utc).replace(tzinfo=None),
    )


class SnWsdWorkshopScreenService(models.AbstractModel):
    """车间展示大屏数据服务。

    面向车间现场挂墙大屏，按车间维度汇总：产线/工位/工单/在制/过站。
    所有数据取真实业务表，不做演示数据填充。
    """

    _name = 'sn.wsd.workshop.screen.service'
    _description = 'Workshop Display Screen Service'

    # ---------------------------------------------------------------- helpers
    @api.model
    def _get_workshop(self, workshop_id=None):
        Workshop = self.env['sn.mrp.workshop']
        workshops = Workshop.search(
            [('active', '=', True)], order='sequence, code, id')
        if not workshops:
            workshops = Workshop.search([], order='id')
        if workshop_id:
            current = workshops.filtered(lambda w: w.id == workshop_id)[:1]
            if current:
                return workshops, current
        return workshops, workshops[:1]

    @api.model
    def _empty_payload(self):
        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        today = fields.Date.context_today(self)
        return {
            'workshops': [],
            'summary': {
                'refresh_time': now.strftime('%Y-%m-%d %H:%M:%S'),
                'today_date': fields.Date.to_string(today),
                'data_date': fields.Date.to_string(today),
                'workshop_name': '未配置车间',
                'line_names': '-',
            },
            'workshop': {},
            'station_flow': [],
            'sales_progress': [],
            'check_summary': {
                'total': 0, 'completed': 0, 'pending': 0, 'overdue': 0,
                'failed': 0, 'rate': 0.0, 'today_total': 0,
                'today_completed': 0, 'equipment_count': 0, 'days': 8,
            },
            'check_equipment': [],
            'defect_top': [],
            'quality_summary': {
                'inspections': 0, 'sample_qty': 0, 'defect_qty': 0,
                'pass_rate': 0.0, 'types': [],
            },
            'quality_daily': [],
            'orders': [],
            'rank': [],
            'trend': [],
            'traces': [],
            'alerts': [],
        }

    # ------------------------------------------------------------- main data
    @api.model
    def get_screen_data(self, workshop_id=None):
        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        today = fields.Date.context_today(self)
        workshops, current = self._get_workshop(workshop_id)
        payload = self._empty_payload()
        payload['workshops'] = [
            {'id': w.id, 'name': w.name or '', 'code': w.code or ''}
            for w in workshops
        ]
        if not current:
            return payload

        History = self.env[HISTORY_MODEL]
        lines = current.production_line_ids
        stations = self.env['mrp.workcenter'].search(
            [('x_workshop_id', '=', current.id)],
            order='x_production_line_id, sequence, id',
        )
        orders = self.env['sn.wsd.mes.order'].search(
            [('x_workshop_id', '=', current.id)], order='id desc', limit=8)
        active_orders = orders.filtered(
            lambda o: o.state not in ('done', 'cancelled'))

        domain_ws = [('mes_order_id.x_workshop_id', '=', current.id)]

        # 数据日期：取最近一条过站记录的本地日期。现场停线/休息日打开大屏时
        # 不会满屏 0，页面顶部会显式标注“数据日期”。
        latest = History.search(
            domain_ws + [('out_date', '!=', False)],
            order='out_date desc', limit=1)
        if latest:
            data_date = fields.Datetime.context_timestamp(
                self, latest.out_date).date()
        else:
            data_date = today

        day_start, day_end = _local_day_bounds(self.env, data_date)
        day_histories = History.search(domain_ws + [
            ('out_date', '>=', day_start),
            ('out_date', '<', day_end),
        ])

        day_stats = {}
        for history in day_histories:
            bucket = day_stats.setdefault(history.workcenter_id.id, {
                'ok': 0, 'ng': 0, 'scrap': 0, 'total': 0,
            })
            bucket['total'] += 1
            if history.result == 'ok':
                bucket['ok'] += 1
            elif history.result == 'ng':
                bucket['ng'] += 1
            elif history.result == 'scrap':
                bucket['scrap'] += 1

        wip_stats = {}
        wips = self.env['sn.wsd.serial.wip'].search(
            [('mes_order_id.x_workshop_id', '=', current.id)])
        for wip in wips:
            wip_stats[wip.workcenter_id.id] = wip_stats.get(
                wip.workcenter_id.id, 0) + 1

        # 工位流转：按产线顺序 + 工位 sequence
        max_day_ok = max((row['ok'] for row in day_stats.values()), default=0)
        station_flow = []
        for station in stations:
            stats = day_stats.get(station.id, {'ok': 0, 'ng': 0, 'scrap': 0, 'total': 0})
            wip_qty = wip_stats.get(station.id, 0)
            if stats['ng'] or stats['scrap']:
                status = 'warning'
            elif wip_qty:
                status = 'running'
            elif stats['total']:
                status = 'normal'
            else:
                status = 'idle'
            station_flow.append({
                'id': station.id,
                'code': station.code or station.name or '-',
                'name': station.name or '',
                'line': station.x_production_line_id.name or '',
                'ok': stats['ok'],
                'ng': stats['ng'] + stats['scrap'],
                'total': stats['total'],
                'wip': wip_qty,
                'load_rate': round(stats['ok'] / max_day_ok * 100.0, 1) if max_day_ok else 0.0,
                'status': status,
            })

        # 近 8 天产出趋势（以数据日期为终点）
        trend_days = [
            data_date - datetime.timedelta(days=offset)
            for offset in range(7, -1, -1)
        ]
        trend_start, _dummy = _local_day_bounds(self.env, trend_days[0])
        _dummy, trend_end = _local_day_bounds(self.env, trend_days[-1])
        trend_histories = History.search(domain_ws + [
            ('out_date', '>=', trend_start),
            ('out_date', '<', trend_end),
        ])
        buckets = {day: {'ok': 0, 'ng': 0} for day in trend_days}
        for history in trend_histories:
            if not history.out_date:
                continue
            day = fields.Datetime.context_timestamp(self, history.out_date).date()
            bucket = buckets.get(day)
            if bucket is None:
                continue
            if history.result == 'ok':
                bucket['ok'] += 1
            elif history.result in ('ng', 'scrap'):
                bucket['ng'] += 1
        trend = [{
            'label': day.strftime('%m-%d'),
            'ok': buckets[day]['ok'],
            'ng': buckets[day]['ng'],
        } for day in trend_days]

        # ---- 订单完成进度（销售订单 → 关联生产订单的实际产出） ----
        sale_orders = self.env['sale.order'].search(
            [('state', 'in', ('sale', 'done'))],
            order='date_order desc, id desc', limit=6)
        sales_progress = []
        for order in sale_orders:
            order_qty = sum(order.order_line.mapped('product_uom_qty')) or 0.0
            mos = self.env['mrp.production'].search(
                [('sale_line_id', 'in', order.order_line.ids)])
            produced = 0.0
            if 'x_mes_produced_qty' in mos._fields:
                produced = sum(mos.mapped('x_mes_produced_qty') or [])
            elif 'qty_producing' in mos._fields:
                produced = sum(mos.mapped('qty_producing') or [])
            if not produced and order.delivery_status == 'full':
                produced = order_qty
            sales_progress.append({
                'name': order.name,
                'partner': order.partner_id.display_name or '-',
                'qty': order_qty,
                'produced': produced,
                'progress': round(min(produced / order_qty * 100.0, 100.0), 1) if order_qty else 0.0,
                'state_label': STATE_LABELS.get(order.state, order.state or ''),
                'date': fields.Date.to_string(order.date_order.date()) if order.date_order else '',
            })

        # ---- 设备点检完成情况（近 8 天） ----
        check_tasks = self.env['sn.wsd.device.check.task'].search([
            ('task_date', '>=', fields.Date.to_string(trend_days[0])),
            ('task_date', '<=', fields.Date.to_string(data_date)),
        ])
        check_completed = check_tasks.filtered(lambda t: t.task_status == 'completed')
        check_failed = check_completed.filtered(lambda t: t.overall_result == 'fail')
        check_pending = check_tasks.filtered(
            lambda t: t.task_status in ('pending', 'in_progress'))
        check_overdue = check_tasks.filtered(lambda t: t.task_status == 'overdue')
        check_total = len(check_tasks)
        check_summary = {
            'days': len(trend_days),
            'total': check_total,
            'completed': len(check_completed),
            'pending': len(check_pending),
            'overdue': len(check_overdue),
            'failed': len(check_failed),
            'rate': round(len(check_completed) / check_total * 100.0, 1) if check_total else 0.0,
            'today_total': len(check_tasks.filtered(lambda t: t.task_date == today)),
            'today_completed': len(
                check_completed.filtered(lambda t: t.task_date == today)),
            'equipment_count': self.env['sn.wsd.device.equipment'].search_count(
                [('equipment_status', '=', 'enabled')]),
        }

        # ---- 设备级点检明细：设备名 + 完成状态（成功 / 不成功） ----
        equipment_rows = {}
        for task in check_tasks:
            equipment = task.equipment_id
            row = equipment_rows.setdefault(equipment.id or 0, {
                'code': equipment.code or '-',
                'name': equipment.name or '未登记设备',
                'total': 0,
                'completed': 0,
                'passed': 0,
                'failed': 0,
                'pending': 0,
                'overdue': 0,
            })
            row['total'] += 1
            if task.task_status == 'completed':
                row['completed'] += 1
                if task.overall_result == 'fail':
                    row['failed'] += 1
                else:
                    row['passed'] += 1
            elif task.task_status == 'overdue':
                row['overdue'] += 1
            else:
                row['pending'] += 1
        check_equipment = []
        for row in equipment_rows.values():
            if row['overdue']:
                status, status_label = 'overdue', '逾期未检'
            elif row['pending']:
                status, status_label = 'pending', '待执行'
            elif row['failed']:
                status, status_label = 'fail', '点检不合格'
            else:
                status, status_label = 'pass', '点检合格'
            row['status'] = status
            row['status_label'] = status_label
            row['rate'] = round(
                row['completed'] / row['total'] * 100.0, 1) if row['total'] else 0.0
            check_equipment.append(row)
        status_order = {'overdue': 0, 'fail': 1, 'pending': 2, 'pass': 3}
        check_equipment.sort(key=lambda row: (
            status_order.get(row['status'], 9), -row['total'], row['code']))

        # ---- 近 8 天 TOP5 不良（质量检验缺陷明细） ----
        defect_lines = self.env['sn.wsd.quality.inspection.defect.line'].search([
            ('inspection_id.finish_time', '>=', trend_start),
            ('inspection_id.finish_time', '<', trend_end),
        ])
        defect_agg = {}
        for line in defect_lines:
            key = line.defect_code_id.id or 0
            row = defect_agg.setdefault(key, {
                'code': line.defect_code_id.code or '-',
                'name': line.defect_code_id.name or '未归类',
                'qty': 0.0,
            })
            row['qty'] += line.defect_qty or 0.0
        defect_total = sum(row['qty'] for row in defect_agg.values())
        defect_top = sorted(
            defect_agg.values(), key=lambda row: row['qty'], reverse=True)[:5]
        max_defect = max((row['qty'] for row in defect_top), default=0)
        for row in defect_top:
            row['ratio'] = round(row['qty'] / max_defect * 100.0, 1) if max_defect else 0.0
            row['share'] = round(row['qty'] / defect_total * 100.0, 1) if defect_total else 0.0

        # ---- 近 8 天质量抽检情况 ----
        inspections = self.env['sn.wsd.quality.inspection'].search([
            ('finish_time', '>=', trend_start),
            ('finish_time', '<', trend_end),
            ('state', '=', 'done'),
        ])
        by_type = {}
        for inspection in inspections:
            key = inspection.inspection_type or 'other'
            row = by_type.setdefault(key, {
                'type': key,
                'label': INSPECTION_TYPE_LABELS.get(key, key),
                'count': 0,
                'sample_qty': 0.0,
                'defect_qty': 0.0,
            })
            row['count'] += 1
            row['sample_qty'] += inspection.inspected_qty or inspection.sample_size or 0
            row['defect_qty'] += inspection.defect_qty or 0
        for row in by_type.values():
            base = row['sample_qty']
            row['pass_rate'] = round(
                (base - row['defect_qty']) / base * 100.0, 1) if base else 0.0
        quality_types = sorted(
            by_type.values(), key=lambda row: row['count'], reverse=True)
        quality_sample = sum(row['sample_qty'] for row in quality_types)
        quality_defect = sum(row['defect_qty'] for row in quality_types)
        quality_summary = {
            'inspections': len(inspections),
            'sample_qty': quality_sample,
            'defect_qty': quality_defect,
            'pass_rate': round(
                (quality_sample - quality_defect) / quality_sample * 100.0, 1
            ) if quality_sample else 0.0,
            'types': quality_types,
        }

        # ---- 近 8 天每日抽检量（条形图数据源） ----
        quality_buckets = {
            day: {'sample': 0.0, 'defect': 0.0, 'count': 0} for day in trend_days
        }
        for inspection in inspections:
            if not inspection.finish_time:
                continue
            day = fields.Datetime.context_timestamp(
                self, inspection.finish_time).date()
            bucket = quality_buckets.get(day)
            if bucket is None:
                continue
            bucket['sample'] += inspection.inspected_qty or inspection.sample_size or 0
            bucket['defect'] += inspection.defect_qty or 0
            bucket['count'] += 1
        quality_daily = []
        for day in trend_days:
            bucket = quality_buckets[day]
            sample = bucket['sample']
            quality_daily.append({
                'label': day.strftime('%m-%d'),
                'sample_qty': sample,
                'defect_qty': bucket['defect'],
                'pass_qty': max(sample - bucket['defect'], 0.0),
                'count': bucket['count'],
                'pass_rate': round(
                    (sample - bucket['defect']) / sample * 100.0, 1
                ) if sample else 0.0,
            })

        # 最近过站流水
        recent = History.search(
            domain_ws + [('out_date', '!=', False)],
            order='out_date desc, id desc', limit=14)
        traces = [{
            'time': fields.Datetime.context_timestamp(
                self, history.out_date).strftime('%m-%d %H:%M'),
            'serial': history.serial_identity_id.name or '-',
            'station': history.workcenter_id.code or history.workcenter_id.name or '-',
            'operation': history.route_operation_id.display_name or '-',
            'result': RESULT_LABELS.get(history.result, history.result or ''),
            'status': 'danger' if history.result in ('ng', 'scrap') else 'normal',
        } for history in recent]

        # 异常清单
        abnormal = History.search(
            domain_ws + [('result', 'in', ('ng', 'scrap')), ('out_date', '!=', False)],
            order='out_date desc, id desc', limit=8)
        alerts = [{
            'time': fields.Datetime.context_timestamp(
                self, history.out_date).strftime('%m-%d %H:%M'),
            'serial': history.serial_identity_id.name or '-',
            'station': history.workcenter_id.code or history.workcenter_id.name or '-',
            'result': RESULT_LABELS.get(history.result, history.result or ''),
        } for history in abnormal]

        day_ok = sum(row['ok'] for row in day_stats.values())
        day_total = sum(row['total'] for row in day_stats.values())
        wip_total = sum(wip_stats.values())
        plan_qty = sum(order.planned_qty or 0.0 for order in active_orders)
        plan_done = sum(order.x_output_qty or 0.0 for order in active_orders)
        completion = (plan_done / plan_qty * 100.0) if plan_qty else 0.0

        rank = sorted(station_flow, key=lambda item: item['ok'], reverse=True)[:8]
        max_rank = max((item['ok'] for item in rank), default=0)
        for item in rank:
            item['ratio'] = round(item['ok'] / max_rank * 100.0, 1) if max_rank else 0.0

        payload.update({
            'summary': {
                'workshop_name': current.name or '',
                'workshop_code': current.code or '',
                'line_names': ', '.join(lines.mapped('name')) or '-',
                'line_count': len(lines),
                'station_count': len(stations),
                'order_count': len(orders),
                'active_order_count': len(active_orders),
                'day_output': day_ok,
                'day_total': day_total,
                'wip_total': wip_total,
                'pass_rate': round(day_ok / day_total * 100.0, 1) if day_total else 0.0,
                'plan_qty': plan_qty,
                'plan_done': plan_done,
                'completion_rate': round(completion, 1),
                'data_date': fields.Date.to_string(data_date),
                'today_date': fields.Date.to_string(today),
                'is_today': data_date == today,
                'refresh_time': now.strftime('%Y-%m-%d %H:%M:%S'),
            },
            'workshop': {
                'id': current.id,
                'name': current.name or '',
                'code': current.code or '',
                'lines': [{
                    'id': line.id,
                    'name': line.name or '',
                    'code': line.code or '',
                    'station_count': len(line.station_ids),
                } for line in lines],
            },
            'station_flow': station_flow,
            'sales_progress': sales_progress,
            'check_summary': check_summary,
            'check_equipment': check_equipment,
            'defect_top': defect_top,
            'quality_summary': quality_summary,
            'quality_daily': quality_daily,
            'orders': [{
                'name': order.name or '',
                'product': order.product_id.display_name or '-',
                'line': order.production_line_id.name or '-',
                'plan_qty': order.planned_qty or 0.0,
                'output_qty': order.x_output_qty or 0.0,
                'input_qty': order.x_input_qty or 0.0,
                'progress': round(
                    (order.x_output_qty or 0.0) / order.planned_qty * 100.0, 1
                ) if order.planned_qty else 0.0,
                'state': order.state,
                'state_label': STATE_LABELS.get(order.state, order.state or ''),
                'date_plan': fields.Date.to_string(order.date_plan) if order.date_plan else '',
            } for order in orders],
            'rank': rank,
            'trend': trend,
            'traces': traces,
            'alerts': alerts,
        })
        return payload

    @api.model
    def action_open_workshop_screen(self):
        client_action = self.env.ref(
            'sn_wsd_report.action_sn_wsd_workshop_screen_client',
            raise_if_not_found=False,
        )
        if client_action:
            action = client_action.read()[0]
            action['name'] = _('Workshop Display Board')
            return action
        return {
            'type': 'ir.actions.client',
            'tag': 'sn_wsd_workshop_screen_action',
            'name': _('Workshop Display Board'),
            'target': 'fullscreen',
            'path': 'sn-wsd-workshop-screen-display',
            'context': {},
        }
