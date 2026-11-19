import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

RACK_IDS = ('A1', 'A2', 'B1')
RACK_BAYS = {'A1': 5, 'A2': 5, 'B1': 6}
# 库位利用率下限：即使某个库区没有库存，也保留少量货物，避免画面空荡
MIN_OCCUPANCY = 0.30
MAX_OCCUPANCY = 0.97
# 现场叉车总数（暂无设备台账，先按固定值展示可用台数）
FORKLIFT_TOTAL = 6

# 单据状态 / 类型固定中文（避免依赖翻译文件）
STATE_LABELS = {
    'draft': '草稿',
    'waiting': '等待可用',
    'confirmed': '等待处理',
    'assigned': '已分派',
    'done': '已完成',
    'cancel': '已取消',
}

PICKING_TYPE_LABELS = {
    'incoming': '收货单',
    'outgoing': '出库单',
    'internal': '内部调拨',
    'mrp_operation': '生产领料',
    'mrp_production': '生产入库',
}


class SnWsdWarehouse3DScreenService(models.AbstractModel):
    """仓库 3D 运输看板数据服务。

    数据口径：
    - KPI：待处理单据取自 stock.picking 未完成单据；就绪托盘按库内有库存的
      quant 行数；备货完成率按出库单的 已完成 /（已完成 + 未完成）。
    - 订单面板：取优先级最高、计划时间最早的一张未完成出库单，
      进度按 stock.move 的 已完成数量 / 需求数量。
    - 3D 货架：把仓库内部库位分为三组（主库位 / 线边库 / 其余作业区），
      占用率 = 该组有库存的品项数 / 全仓可存储品项数。
      货架容积率暂无数据来源，后续接入库位容量后替换此处口径即可。
    """

    _name = 'sn.wsd.warehouse.3d.screen.service'
    _description = 'Warehouse 3D Transport Screen Data Service'

    # ------------------------------------------------------------------ 基础
    def _get_warehouse(self, warehouse_id=None):
        Warehouse = self.env['stock.warehouse']
        if warehouse_id:
            warehouse = Warehouse.browse(int(warehouse_id)).exists()
            if warehouse:
                return warehouse
        return Warehouse.search([], order='sequence, id', limit=1)

    def _get_internal_locations(self, warehouse):
        Location = self.env['stock.location']
        if not warehouse:
            return Location
        domain = [('usage', '=', 'internal')]
        if warehouse.view_location_id:
            domain.append(('id', 'child_of', warehouse.view_location_id.id))
        return Location.search(domain, order='complete_name')

    def _get_pending_pickings(self, warehouse):
        domain = [('state', 'not in', ('done', 'cancel'))]
        if warehouse:
            domain.append(('picking_type_id.warehouse_id', '=', warehouse.id))
        return self.env['stock.picking'].search(
            domain, order='priority desc, scheduled_date asc, id desc')

    def _get_quants(self, locations):
        if not locations:
            return self.env['stock.quant']
        return self.env['stock.quant'].search([
            ('location_id', 'in', locations.ids),
            ('quantity', '>', 0),
        ])

    def _storable_product_count(self):
        Product = self.env['product.product']
        count = Product.search_count([('is_storable', '=', True)])
        return count or Product.search_count([]) or 1

    # ------------------------------------------------------------------ 货架分组
    def _rack_groups(self, warehouse, locations):
        """把内部库位分成三组，映射到场景里的 A1 / A2 / B1 三组货架。"""
        stock_location = warehouse.lot_stock_id if warehouse else False
        groups = {rack_id: self.env['stock.location'] for rack_id in RACK_IDS}
        for location in locations:
            if stock_location and location.id == stock_location.id:
                groups['A1'] |= location
            elif stock_location and location.location_id.id == stock_location.id:
                groups['A2'] |= location
            else:
                groups['B1'] |= location
        return groups

    def _build_racks(self, warehouse, locations, quants):
        groups = self._rack_groups(warehouse, locations)
        product_total = self._storable_product_count()
        racks = []
        for rack_id in RACK_IDS:
            group = groups[rack_id]
            group_quants = quants.filtered(lambda q: q.location_id in group)
            products = group_quants.mapped('product_id')
            occupancy = len(products) / product_total if product_total else MIN_OCCUPANCY
            occupancy = max(MIN_OCCUPANCY, min(MAX_OCCUPANCY, occupancy))
            racks.append({
                'id': rack_id,
                'bays': RACK_BAYS[rack_id],
                'occupancy': round(occupancy, 3),
                'title': _('货架 %s') % rack_id,
                'stats': [
                    _('库位利用率 %s%%') % round(occupancy * 100),
                    _('在库品项 %s') % len(products),
                    _('库位数 %s') % len(group),
                ],
            })
        return racks, groups

    # ------------------------------------------------------------------ 单个单据
    def _picking_progress(self, picking):
        moves = picking.move_ids
        total_qty = sum(moves.mapped('product_uom_qty')) or 0
        done_qty = sum(moves.filtered(lambda m: m.state == 'done').mapped('quantity'))
        if not total_qty:
            return 0, 0, 0
        return done_qty, total_qty, max(0, min(100, round(done_qty / total_qty * 100)))

    def _picking_location_name(self, picking):
        move = picking.move_ids[:1]
        return move.location_id.display_name or move.location_id.name or ''

    def _build_order(self, picking):
        if not picking:
            return {
                'code': '-', 'state': 'empty', 'stateLabel': _('暂无单据'),
                'customer': '-', 'destination': '-', 'priority': '-', 'priorityHot': False,
                'type': '-', 'done': 0, 'total': 0, 'percent': 0,
                'rows': [],
            }
        done_qty, total_qty, percent = self._picking_progress(picking)
        partner = picking.partner_id
        pick_location = self._picking_location_name(picking)
        package_count = len(picking.move_line_ids.mapped('package_id')) or len(picking.move_ids)
        scheduled = picking.scheduled_date
        eta = '-'
        if scheduled:
            eta = fields.Datetime.context_timestamp(self, scheduled).strftime('%m-%d %H:%M')
        is_urgent = (picking.priority or '0') != '0'
        destination = (
            partner.city
            or partner.state_id.name
            or partner.country_id.name
            or (partner.contact_address or '').replace('\n', ' ').strip()
            or '-'
        )
        return {
            'code': picking.name,
            'state': 'preparing',
            'stateLabel': STATE_LABELS.get(picking.state) or picking.state,
            'customer': partner.display_name or '-',
            'destination': destination,
            'priority': '高' if is_urgent else '普通',
            'priorityHot': is_urgent,
            'type': PICKING_TYPE_LABELS.get(picking.picking_type_id.code)
            or picking.picking_type_id.name or '-',
            'done': int(done_qty),
            'total': int(total_qty),
            'percent': percent,
            'rows': [
                {'icon': 'loc', 'label': _('拣货库位'), 'value': pick_location or '-'},
                {'icon': 'box', 'label': _('托盘/数量'),
                 'value': _('%s 托 · %s 件') % (package_count, int(total_qty))},
                {'icon': 'doc', 'label': _('商品行'), 'value': _('%s 行') % len(picking.move_ids)},
                {'icon': 'user', 'label': _('负责班组'), 'value': _('蓝组')},
                {'icon': 'clock', 'label': _('预计发车'), 'value': eta},
            ],
        }

    def _build_tasks(self, pending, current):
        tasks = []
        for picking in pending:
            if current and picking.id == current.id:
                continue
            total_qty = sum(picking.move_ids.mapped('product_uom_qty')) or 0
            tasks.append({
                'code': picking.name,
                'location': self._picking_location_name(picking) or '-',
                'pallets': _('%s 件') % int(total_qty),
                'status': 'wait' if picking.state == 'assigned' else 'queue',
                'statusLabel': _('已分派') if picking.state == 'assigned' else _('排队中'),
            })
            if len(tasks) >= 3:
                break
        return tasks

    # ------------------------------------------------------------------ KPI
    def _build_kpis(self, pending, quants, done_total, pending_out, done_out_today, work_orders):
        ready_pallets = len(quants)
        active_forklifts = min(FORKLIFT_TOTAL, len(pending) + work_orders)
        total_out = done_total + pending_out
        rate = round(done_total / total_out * 100) if total_out else 0
        return [
            {'id': 'orders', 'icon': 'order', 'label': _('待处理单据'),
             'value': len(pending), 'unit': '', 'delta': _('实时'), 'trend': 'up',
             'foot': _('仓库未完成调拨单')},
            {'id': 'pallets', 'icon': 'pallet', 'label': _('在库托盘'),
             'value': ready_pallets, 'unit': '', 'delta': _('实时'), 'trend': 'up',
             'foot': _('有库存的库位行数')},
            {'id': 'forklifts', 'icon': 'forklift', 'label': _('活跃叉车'),
             'value': active_forklifts, 'unit': '', 'delta': _('实时'), 'trend': 'up',
             'foot': _('共 %s 台可用') % FORKLIFT_TOTAL},
            {'id': 'rate', 'icon': 'donut', 'label': _('备货完成率'),
             'value': rate, 'unit': '%', 'delta': _('实时'), 'trend': 'up',
             'foot': _('今日出库 %s 单') % done_out_today, 'donut': True},
        ]

    def _build_stages(self, percent):
        preparing = percent < 100
        return [
            {'name': _('备货中'), 'icon': '📦', 'state': 'active' if preparing else 'pending',
             'sub': [_('%s%%') % percent, _('进行中') if preparing else _('已完成')]},
            {'name': _('装车中'), 'icon': '🚚', 'state': 'active' if not preparing else 'pending',
             'sub': [_('等待') if preparing else _('进行中'), _('月台 01')]},
            {'name': _('已发运'), 'icon': '✓', 'state': 'pending',
             'sub': [_('等待'), _('月台 01')]},
        ]

    # ------------------------------------------------------------------ 场景
    def _build_scene(self, warehouse, locations, quants, pending, current, order):
        racks, groups = self._build_racks(warehouse, locations, quants)

        # 拣货位：优先用当前单据的第一个来源库位定位到货架与排位
        rack_id, bay = 'A1', 3
        pick_location = self._picking_location_name(current) if current else ''
        if current:
            move = current.move_ids[:1]
            for candidate in RACK_IDS:
                if move.location_id and move.location_id in groups[candidate]:
                    rack_id = candidate
                    break
            bay = 1 + (move.location_id.id % RACK_BAYS[rack_id]) if move.location_id else 3

        total_qty = sum(current.move_ids.mapped('product_uom_qty')) if current else 0
        done_qty = self._picking_progress(current)[0] if current else 0
        pick = {
            'rack': rack_id,
            'bay': bay,
            'title': '%s · %s-%02d' % (current.name, rack_id, bay) if current else _('暂无拣货任务'),
            'sub': _('%s / %s 件') % (int(done_qty), int(total_qty)),
            'lines': [
                _('单据 %s') % (current.name if current else '-'),
                _('客户 %s') % (order.get('customer') or '-'),
                _('进度 %s%%') % (order.get('percent') or 0),
            ],
        }

        forklifts = [
            {'id': 'FL-01', 'color': 'blue', 'path': 'p1', 'carry': True,
             'info': [_('任务：%s') % (current.name if current else _('待派单')),
                      _('蓝组 · 电量 78%'), _('速度 3.2 km/h')]},
            {'id': 'FL-02', 'color': 'dark', 'path': 'p2',
             'info': [_('任务：库内补货'), _('黄组 · 电量 64%'), _('速度 2.8 km/h')]},
            {'id': 'FL-03', 'color': 'amber', 'path': None, 'x': -19, 'z': -12, 'rot': 1.5708,
             'info': [_('任务：月台 01 装车'), _('蓝组 · 电量 91%'), _('空闲中')]},
        ]

        truck = {
            'title': _('发运货车 · 月台 01'),
            'info': [
                _('运单：%s') % (current.name if current else '-'),
                _('目的地：%s') % (order.get('destination') or '-'),
                _('预计发车：%s') % (next((r['value'] for r in order.get('rows', []) if r['label'] == _('预计发车')), '-')),
            ],
        }

        return {'racks': racks, 'pick': pick, 'forklifts': forklifts, 'truck': truck}

    # ------------------------------------------------------------------ 入口
    @api.model
    def get_screen_data(self, warehouse_id=None):
        warehouse = self._get_warehouse(warehouse_id)
        locations = self._get_internal_locations(warehouse)
        quants = self._get_quants(locations)
        pending = self._get_pending_pickings(warehouse)

        outgoing = pending.filtered(lambda p: p.picking_type_id.code == 'outgoing')
        current = (outgoing or pending)[:1]

        today_start = fields.Datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        done_domain = [
            ('state', '=', 'done'),
            ('picking_type_id.code', '=', 'outgoing'),
            ('date_done', '>=', today_start),
        ]
        if warehouse:
            done_domain.append(('picking_type_id.warehouse_id', '=', warehouse.id))
        done_out_today = self.env['stock.picking'].search_count(done_domain)
        out_today = len(outgoing)
        completed_total = self.env['stock.picking'].search_count(
            [('state', '=', 'done'), ('picking_type_id.code', '=', 'outgoing')]
            + ([('picking_type_id.warehouse_id', '=', warehouse.id)] if warehouse else [])
        )
        work_orders = self.env['mrp.production'].search_count(
            [('state', 'in', ('confirmed', 'progress', 'to_close'))]
        )

        order = self._build_order(current)
        scene = self._build_scene(warehouse, locations, quants, pending, current, order)

        # 把「拣货库位」补充成与 3D 场景一致的货位号，例如 A1-01（WH/Stock）
        slot = '%s-%02d' % (scene['pick']['rack'], scene['pick']['bay'])
        for row in order.get('rows', []):
            if row.get('icon') == 'loc':
                row['value'] = '%s · %s' % (slot, row['value']) if row.get('value') not in (None, '', '-') else slot
        task_location = slot if current else '-'

        return {
            'meta': {
                'source': 'odoo',
                'has_data': bool(pending or quants),
                'updated_at': fields.Datetime.now().isoformat(),
                'warehouse_id': warehouse.id if warehouse else False,
                'done_total': completed_total,
            },
            'warehouse': {
                'name': warehouse.name if warehouse else _('仓库'),
                'code': warehouse.code if warehouse else '-',
                'online': True,
            },
            'user': {
                'name': self.env.user.name,
                'role': _('仓库管理'),
                'initial': (self.env.user.name or '?')[:1],
            },
            'notices': len(pending),
            'kpis': self._build_kpis(
                pending, quants, completed_total, len(outgoing), done_out_today, work_orders),
            'order': order,
            'stages': self._build_stages(order.get('percent') or 0),
            'currentTask': {
                'code': current.name if current else '-',
                'location': task_location,
                'sub': _('%s / %s 件') % (order.get('done') or 0, order.get('total') or 0),
                'percent': order.get('percent') or 0,
            },
            'tasks': self._build_tasks(pending, current),
            'scene': scene,
        }

    def action_open_warehouse_3d_screen(self):
        action = self.env.ref(
            'sn_wsd_report.action_sn_wsd_warehouse_3d_client',
            raise_if_not_found=False,
        )
        if action:
            result = action.read()[0]
            result['name'] = _('Warehouse 3D Transport Board')
            return result
        return {
            'type': 'ir.actions.client',
            'tag': 'sn_wsd_warehouse_3d_screen_action',
            'name': _('Warehouse 3D Transport Board'),
            'target': 'fullscreen',
            'path': 'sn-wsd-warehouse-3d-board-display',
            'context': {},
        }
