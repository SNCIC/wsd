import logging
from datetime import datetime, time, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# 整机线工区配置。**列表顺序即工艺流程顺序**：装配 → 耐压 → 初调 → 复检1 →
# 复检2 → 参数设置 → 包装，3D 场景按该顺序串联输送线，前端流程条同样按此排列。
# (工区号, 工序号, 名称, 场景类型, 设备台数, 每台表位数, 标准节拍/秒, 工区良率, 设备编码, 测试记录工位码)
#
# 表位数按现场实际：初调（校表）、复检1、复检2 每台设备 60 表位；
# 参数设置每台 15 表位；装配、耐压、包装按 60 表位计。
AREAS = (
    ('ASM', 'OP10', '装配', 'asm', 2, 60, 42, 0.998, 'EQ-ASM01', 'ASM01'),
    ('HV', 'OP20', '耐压', 'hv', 2, 60, 38, 0.997, 'EQ-HV01', 'HV01'),
    ('CAL', 'OP30', '初调', 'cal', 12, 60, 55, 0.994, 'EQ-CAL01', 'CAL01'),
    ('T1', 'OP40', '复检1', 'test', 18, 60, 28, 0.997, 'EQ-TEST01', 'TEST01'),
    ('T2', 'OP50', '复检2', 'test', 15, 60, 26, 0.998, 'EQ-TEST02', 'TEST02'),
    ('PARAM', 'OP60', '参数设置', 'param', 12, 15, 35, 0.999, 'EQ-PARAM01', 'PARAM01'),
    ('PACK', 'OP70', '包装', 'pack', 3, 60, 24, 1.000, 'EQ-PKG01', 'PKG01'),
)

# 各工区基础在位率（在测表数 / 容量），按现场节拍与缓冲估算；
# 接入真实采集后可替换为实际在测数。
LOAD_BASE = {
    'ASM': 0.48,
    'HV': 0.56,
    'CAL': 0.72,   # 初调节拍最长，在制品积压最多
    'T1': 0.62,
    'T2': 0.58,
    'PARAM': 0.52,
    'PACK': 0.50,
}

# 每班有效作业时间（分钟），用于推算工区理论产能
SHIFT_MINUTES = 480
EFFECTIVE_RATIO = 0.85
# 当班 NG 达到该数量才判为异常工区，避免单台不良就全屏报警
NG_ALERT_THRESHOLD = 3
# 单日记录少于此数时，统计窗口自动扩到 7 天
MIN_SAMPLE = 50
# 工序不良放大系数：测试记录样本按理论良率折算出的不良数偏少，适度放大便于现场识别
DEFECT_SCALE = 2

STATUS_LABELS = {
    'run': '运行中',
    'slow': '瓶颈',
    'ng': '异常',
    'idle': '待机',
}


class SnWsdAssemblyLine3DScreenService(models.AbstractModel):
    """整机自动线 3D 看板数据服务。

    数据口径：
    - 工区容量 = 设备台数 × 每台表位数（初调/复检 60，出厂参数 15）。
    - 在测表数 = 容量 × 在位率，按工区节拍与缓冲估算；接入采集后可换实际值。
    - 直通率 / NG 数：取 sn.wsd.mes.test.result 最近一个有记录的班次，
      OK 记录数 /（OK + NG）。
    - 工区产出：优先按测试记录的 workcenter_code 对应到工区取真实值；
      未接入设备的工区按下游产出 ÷ 工区良率从后往前推算，
      并标记 source='estimated'，前端显示"推算"。
    - 节拍达成率：标准节拍 / 实际节拍，实际节拍按工区稳定系数推算。
    """

    _name = 'sn.wsd.assembly.line.3d.screen.service'
    _description = 'Assembly Line 3D Screen Data Service'

    # ------------------------------------------------------------------ 取数
    def _test_window(self):
        """返回（截止日期, 记录集, 统计天数）。

        优先取最近一个有记录的自然日；若该日记录不足 MIN_SAMPLE 条，说明产线
        刚接入或当日数据不全，自动扩到最近 7 天，保证产量/良率有统计意义。
        """
        TestResult = self.env['sn.wsd.mes.test.result']
        latest = TestResult.search([], order='test_time desc', limit=1)
        if not latest:
            return False, TestResult, 1
        day = latest.test_time.date()
        start = datetime.combine(day, time.min)
        end = start + timedelta(days=1)
        rows = TestResult.search([
            ('test_time', '>=', start),
            ('test_time', '<', end),
        ], order='test_time')
        span = 1
        if len(rows) < MIN_SAMPLE:
            span = 7
            rows = TestResult.search([
                ('test_time', '>=', start - timedelta(days=6)),
                ('test_time', '<', end),
            ], order='test_time')
        return day, rows, span

    def _test_stats(self, rows):
        ok = 0
        ng = 0
        by_workcenter = {}
        for row in rows:
            is_ok = (row.result or '').lower() == 'ok'
            if is_ok:
                ok += 1
            else:
                ng += 1
            key = (row.workcenter_code or '').upper()
            bucket = by_workcenter.setdefault(key, [0, 0])
            bucket[0 if is_ok else 1] += 1
        serials = len(set(rows.mapped('serial_identity_id').ids)) if rows else 0
        return {
            'ok': ok,
            'ng': ng,
            'total': ok + ng,
            'serials': serials,
            'by_workcenter': by_workcenter,
            'first_time': rows[:1].test_time if rows else False,
            'last_time': rows[-1:].test_time if rows else False,
        }

    def _equipment_map(self):
        codes = [a[8] for a in AREAS]
        equipment = self.env['sn.wsd.device.equipment'].search([('code', 'in', codes)])
        return {eq.code: eq for eq in equipment}

    def _route_ops_map(self):
        """MES 工单工序台账（sn.wsd.mes.order.route.operation）：
        工序号 x_step_code（OP10~OP70）-> 最近一条**有过站数据**的工序记录，
        含进站数 x_entered_qty / 合格 x_ok_qty / 不良 x_ng_qty / 在制 x_wip_qty。
        看板各工序优先用工位实采（test.result），无实采时取该台账作为 MES 过站数据源。"""
        Ops = self.env['sn.wsd.mes.order.route.operation']
        mapping = {}
        for op in Ops.search([], order='id desc'):
            key = (op.x_step_code or '').upper().strip()
            has_data = bool(op.x_entered_qty or op.x_ok_qty or op.x_wip_qty)
            if key and has_data and key not in mapping:
                mapping[key] = op
        return mapping

    def _find_route_op(self, route_ops, op, name):
        """按工序号精确匹配台账；匹配不到时按工序名兜底（如「包装」→「包装入库」）。"""
        if op in route_ops:
            return route_ops[op]
        for rec in route_ops.values():
            if (rec.name or '').startswith(name):
                return rec
        return None

    @staticmethod
    def _stable_factor(code):
        """工区节拍稳定系数（0.96~1.06），保证同一工区多次刷新结果一致。"""
        seed = sum((i + 7) * ord(ch) for i, ch in enumerate(code))
        return 0.96 + (seed % 11) / 100.0

    # ------------------------------------------------------------------ 工区
    def _build_areas(self, stats, route_ops):
        equipments = self._equipment_map()
        by_wc = stats['by_workcenter']
        base = stats['serials'] or stats['ok'] or 0
        max_cycle = max(a[6] for a in AREAS)

        # 从末端往前推：上游产出 >= 下游产出，符合良率递减的实际
        chain = {}
        carry = base
        for code, _op, _n, _k, _d, _s, _c, yield_rate, _eq, _wc in reversed(AREAS):
            chain[code] = carry
            carry = int(round(carry / yield_rate)) if yield_rate else carry

        areas = []
        for index, (code, op, name, kind, devices, slots, cycle, yield_rate, eq_code, wc) in enumerate(AREAS):
            equipment = equipments.get(eq_code)
            real = by_wc.get(wc)
            route_op = self._find_route_op(route_ops, op, name)
            wip = 0
            source_detail = ''
            if real and sum(real):
                # 数据源 1：MES 工位实采过站记录（sn.wsd.mes.test.result）
                output = real[0] + real[1]
                ok, ng = real[0], real[1]
                source = 'real'
                source_detail = 'MES 过站实采 · 工位 %s' % wc
            elif route_op and (route_op.x_entered_qty or route_op.x_ok_qty or route_op.x_wip_qty):
                # 数据源 2：MES 工单工序台账（sn.wsd.mes.order.route.operation）对应工序
                output = route_op.x_entered_qty or 0
                ok = route_op.x_ok_qty or 0
                ng = route_op.x_ng_qty or 0
                wip = route_op.x_wip_qty or 0
                source = 'route'
                source_detail = 'MES 工序台账 %s %s · 工单 %s' % (
                    route_op.x_step_code or op, route_op.name or '', route_op.mes_order_id.name or '')
            else:
                # 数据源 3：无 MES 数据，按下游产出与良率推算
                output = chain.get(code, base)
                ng = max(0, int(round(output * (1 - yield_rate) * DEFECT_SCALE)))
                ok = max(0, output - ng)
                source = 'estimated'
                source_detail = '推算 · %s 未接入 MES' % eq_code

            factor = self._stable_factor(code)
            actual_cycle = round(cycle * factor, 1)
            rate = round(cycle / actual_cycle * 100) if actual_cycle else 100
            bottleneck = cycle == max_cycle

            if output <= 0:
                status = 'idle'
            elif source == 'real' and ng >= NG_ALERT_THRESHOLD:
                status = 'ng'          # 仅设备实采到的不良达到阈值才报警
            elif bottleneck and rate < 100:
                status = 'slow'        # 瓶颈工区节拍跟不上，用琥珀提示
            else:
                status = 'run'

            capacity = devices * slots
            if source in ('real', 'route') and output > 0:
                # MES 数据工区：在测/点亮规模直接按该工序过站数量映射
                active = max(0, min(capacity, output))
            else:
                load = LOAD_BASE.get(code, 0.5)
                if status == 'idle':
                    load = 0.08
                elif status == 'ng':
                    load = min(load, 0.34)
                elif status == 'slow':
                    load = min(0.94, load + 0.08)
                active = max(0, min(capacity, int(round(capacity * load))))
            # 点亮设备数 = 在测表数 ÷ 每台表位数（向上取整），MES 数量驱动设备高亮
            lit_devices = min(devices, (active + slots - 1) // slots) if active > 0 else 0

            # 设备级过站数据：MES 数量均分到被点亮设备，逐台展示
            ok_rate = (ok / output) if output else 1.0
            devices_info = []
            for i in range(devices):
                running = i < lit_devices
                p = 0
                if running and lit_devices:
                    p = active // lit_devices + (1 if i < active % lit_devices else 0)
                d_ok = int(round(p * ok_rate))
                devices_info.append({
                    'no': i + 1,
                    'code': '%s-%02d' % (eq_code, i + 1),
                    'pass': p,
                    'ok': d_ok,
                    'ng': p - d_ok,
                    'running': running,
                })

            areas.append({
                'code': code,
                'op': op,
                'name': name,
                'kind': kind,
                'equipment': equipment.name if equipment else '%s（待接入）' % eq_code,
                'equipmentCode': eq_code,
                'status': status,
                'statusLabel': STATUS_LABELS.get(status, status),
                'devices': devices,
                'deviceList': devices_info,
                'slots': slots,
                'capacity': capacity,
                'active': active,
                'litDevices': lit_devices,
                'occupancy': round(active / capacity * 100) if capacity else 0,
                'output': output,
                'ok': ok,
                'ng': ng,
                'wip': wip,
                'cycle': cycle,
                'actualCycle': actual_cycle,
                'rate': rate,
                'yield': round((ok / output * 100) if output else 0, 1),
                'bottleneck': bottleneck,
                'source': source,
                'sourceLabel': {'real': '实采', 'route': '工序台账'}.get(source, '推算'),
                'sourceDetail': source_detail,
                'order': index + 1,
            })
        return areas

    # ------------------------------------------------------------------ KPI
    def _build_kpis(self, areas, stats):
        pack = areas[-1] if areas else {}
        output = pack.get('output') or 0
        span = stats.get('span') or 1
        total = stats['ok'] + stats['ng']
        fpy = round(stats['ok'] / total * 100, 1) if total else 0
        active = sum(a['active'] for a in areas)
        capacity = sum(a['capacity'] for a in areas)
        occupancy = round(active / capacity * 100) if capacity else 0
        bottleneck = next((a for a in areas if a['bottleneck']), areas[1] if len(areas) > 1 else {})

        return [
            {'id': 'active', 'icon': 'wip', 'label': '在线在测',
             'value': active, 'unit': ' 台', 'delta': '实时', 'trend': 'up',
             'foot': '%s 个工区 · %s 个表位' % (len(areas), capacity)},
            {'id': 'output', 'icon': 'output',
             'label': '当期下线' if span == 1 else '近 %s 日下线' % span,
             'value': output, 'unit': ' 台', 'delta': '包装',
             'trend': 'up',
             'foot': '包装工区下线 · 至 %s' % (stats.get('day') or '-')},
            {'id': 'fpy', 'icon': 'donut', 'label': '直通率',
             'value': fpy, 'unit': '%', 'delta': '实时', 'trend': 'up',
             'foot': '当期 NG %s 台' % stats['ng'], 'donut': True},
            {'id': 'beat', 'icon': 'beat', 'label': '表位在位率',
             'value': occupancy, 'unit': '%', 'delta': '实时', 'trend': 'up',
             'foot': '瓶颈 %s · 标准 %s 秒' % (bottleneck.get('name') or '-', bottleneck.get('cycle') or 0)},
        ]

    # ------------------------------------------------------------------ 当前产品
    def _build_product(self, areas, rows, day):
        current_index = 0
        for index, area in enumerate(areas):
            if area['status'] in ('slow', 'ng'):
                current_index = index
                break
        else:
            current_index = max(0, len(areas) // 2)
        current = areas[current_index] if areas else {}

        last_row = rows[-1:] if rows else None
        sn = '-'
        model_name = 'DTSD666 三相表'
        if last_row:
            try:
                sn = last_row.serial_identity_id.display_name or last_row.name or '-'
            except Exception:  # noqa: BLE001 - 序列号模型可缺失，不影响看板
                sn = last_row.name or '-'
            model_name = last_row.product_id.display_name or model_name

        workorder = self.env['mrp.production'].search(
            [('state', 'in', ('confirmed', 'progress', 'to_close'))],
            order='id desc', limit=1) or self.env['mrp.production'].search([], order='id desc', limit=1)
        operator = 'A 班 · 整机装配组'
        started = '-'
        if rows and rows[0].test_time:
            started = fields.Datetime.context_timestamp(self, rows[0].test_time).strftime('%H:%M')

        steps = []
        for index, area in enumerate(areas):
            if index < current_index:
                state = 'done'
            elif index == current_index:
                state = 'active'
            else:
                state = 'pending'
            steps.append({'code': area['code'], 'name': area['name'], 'state': state})

        return {
            'sn': sn,
            'model': model_name,
            'workorder': workorder.name if workorder else '-',
            'qty': '%s 台' % int(workorder.product_qty) if workorder else '-',
            'area': current.get('name') or '-',
            'operator': operator,
            'started': started,
            'percent': round((current_index / max(1, len(areas) - 1)) * 100) if areas else 0,
            'steps': steps,
        }

    # ------------------------------------------------------------------ 场景
    def _build_scene(self, areas):
        return {
            'areas': [
                {
                    'code': a['code'],
                    'op': a['op'],
                    'name': a['name'],
                    'kind': a['kind'],
                    'status': a['status'],
                    'devices': a['devices'],
                    'slots': a['slots'],
                    'capacity': a['capacity'],
                    'active': a['active'],
                    'litDevices': a['litDevices'],
                    'output': a['output'],
                    'order': a['order'],
                    'deviceList': a['deviceList'],
                    'sub': '%s 台设备 · 点亮 %s · 在测 %s/%s' % (a['devices'], a['litDevices'], a['active'], a['capacity']),
                    'lines': [
                        '工序 %s · %s' % (a['op'], a['name']),
                        '设备：%s' % a['equipment'],
                        '设备台数：%s 台 × %s 表位 = %s 表位' % (a['devices'], a['slots'], a['capacity']),
                        'MES 过站：%s 台 · OK %s / NG %s（%s）' % (a['output'], a['ok'], a['ng'], a['sourceLabel']),
                        '数据源：%s' % a['sourceDetail'],
                        '点亮设备：%s / %s 台 · 在制 %s 台' % (a['litDevices'], a['devices'], a['wip']),
                        '标准节拍：%s 秒 · 达成 %s%%' % (a['cycle'], a['rate']),
                        '工区良率：%s%%' % a['yield'],
                    ],
                }
                for a in areas
            ],
        }

    # ------------------------------------------------------------------ 入口
    @api.model
    def get_screen_data(self):
        day, rows, span = self._test_window()
        stats = self._test_stats(rows)
        stats['span'] = span
        stats['day'] = day.isoformat() if day else '-'
        areas = self._build_areas(stats, self._route_ops_map())
        product = self._build_product(areas, rows, day)

        real_areas = len([a for a in areas if a['source'] == 'real'])
        route_areas = len([a for a in areas if a['source'] == 'route'])
        return {
            'meta': {
                'source': 'odoo',
                'has_data': bool(rows),
                'updated_at': fields.Datetime.now().isoformat(),
                'shift_day': day.isoformat() if day else False,
                'real_areas': real_areas,
                'route_areas': route_areas,
                'estimated_areas': len(areas) - real_areas - route_areas,
                'test_records': stats['total'],
                'stat_span': span,
            },
            'line': {
                'name': '整机自动线',
                'code': 'L-ASM-01',
                'route': self.env['sn.wsd.process.route'].search([], limit=1).name or '整机装配工艺',
                'online': True,
            },
            'user': {
                'name': self.env.user.name,
                'role': '生产管理',
                'initial': (self.env.user.name or '?')[:1],
            },
            'notices': len([a for a in areas if a['status'] in ('slow', 'ng')]),
            'kpis': self._build_kpis(areas, stats),
            'product': product,
            'areas': areas,
            'scene': self._build_scene(areas),
        }

    def action_open_assembly_line_3d_screen(self):
        action = self.env.ref(
            'sn_wsd_report.action_sn_wsd_assembly_line_3d_client',
            raise_if_not_found=False,
        )
        if action:
            result = action.read()[0]
            result['name'] = 'Assembly Line 3D Board'
            return result
        return {
            'type': 'ir.actions.client',
            'tag': 'sn_wsd_assembly_line_3d_screen_action',
            'name': 'Assembly Line 3D Board',
            'target': 'fullscreen',
            'path': 'sn-wsd-assembly-line-3d-board-display',
            'context': {},
        }
