from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, freeze_time, tagged


@tagged('post_install', '-at_install')
class TestPassHistoryLedger(TransactionCase):
    """pass-history-on-enter：进站即立 in_progress 历史行（与 WIP 同事务），
    出站回填既有行（判定/出站时间/操作员/NG 缺陷码同行）；完成态语义
    （次数上限/可达性/产出/封板）对在制行不可见；维修截断对空 out_date
    安全。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create({
            'name': 'WS-PHL', 'code': 'WPHL'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'PHL', 'code': 'PHL', 'workshop_id': cls.workshop.id,
        })
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-PHL', 'code': 'RTPHL',
                'x_workshop_id': cls.workshop.id,
            })
        Operation = cls.env['sn.wsd.operation']
        cls.op_a = Operation.create({
            'name': 'PH-A', 'code': 'PHA', 'x_station_type': 'assembly',
            'x_max_test_count': 9})
        cls.op_b = Operation.create({
            'name': 'PH-B', 'code': 'PHB', 'x_station_type': 'final_test',
            'x_max_test_count': 3})
        cls.op_c = Operation.create({
            'name': 'PH-C', 'code': 'PHC', 'x_station_type': 'final_test',
            'x_max_test_count': 3})
        cls.route.write({
            'state': 'confirmed',
            'x_production_side': 'single',
            'route_operation_ids': [
                (0, 0, {'operation_id': cls.op_a.id, 'sequence': 10}),
                (0, 0, {'operation_id': cls.op_b.id, 'sequence': 20}),
                (0, 0, {'operation_id': cls.op_c.id, 'sequence': 30}),
            ],
            'x_daily_input_operation_id': cls.op_a.id,
            'x_daily_output_operation_id': cls.op_b.id,
            'x_workorder_input_operation_id': cls.op_a.id,
        })
        cls.env['sn.wsd.process.route.drawing'].create({
            'route_id': cls.route.id, 'x_drawing_no': 'DWG-PHL'})
        route_ops = cls.route.route_operation_ids.sorted('sequence')
        route_ops[0].x_allow_entry = True
        route_ops[2].x_allow_exit = True
        route_ops[1].blocked_by_route_operation_ids = [(6, 0, route_ops[0].ids)]
        route_ops[2].blocked_by_route_operation_ids = [(6, 0, route_ops[1].ids)]
        cls.defect_code = cls.env['sn.wsd.quality.defect.code'].search(
            [('company_id', 'in', [cls.company.id, False])], limit=1)
        if not cls.defect_code:
            cls.defect_code = cls.env['sn.wsd.quality.defect.code'].create({
                'name': 'PHL Defect', 'code': 'PHLD',
                'category': 'other', 'severity': 'minor',
            })
        cls.scrap_reason = cls.env['sn.wsd.scrap.reason'].search(
            [('company_id', 'in', [cls.company.id, False])], limit=1)
        if not cls.scrap_reason:
            cls.scrap_reason = cls.env['sn.wsd.scrap.reason'].create({
                'name': 'PHL Scrap', 'code': 'PHSCR'})

    # ------------------------------------------------------------------
    # fixtures
    # ------------------------------------------------------------------

    def _make_order_online(self, product=False, qty=4):
        if not product:
            product = self.env['product.product'].create({
                'name': 'P-PHL', 'uom_id': self.uom_unit.id,
                'default_code': 'DWG-PHL', 'x_board_side': 'single',
            })
        mo = self.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': max(10, qty),
            'bom_id': product.bom_ids[:1].id if product.bom_ids else False,
            'company_id': self.company.id,
        })
        order = self.env['sn.wsd.mes.order'].create({
            'production_id': mo.id,
            'production_line_id': self.line.id,
            'date_plan': fields.Date.today(),
            'planned_qty': qty,
        })
        from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
        give_pick(self.env, order)
        order.action_online()
        return order

    def _make_workcenter(self, operation):
        return self.env['mrp.workcenter'].create({
            'name': 'WC-%s' % operation.code,
            'x_workshop_id': self.workshop.id,
            'x_operation_id': operation.id,
            'x_production_line_id': self.line.id,
        })

    def _wcs(self):
        return {'a': self._make_workcenter(self.op_a),
                'b': self._make_workcenter(self.op_b),
                'c': self._make_workcenter(self.op_c)}

    def _rop(self, order, operation):
        return order.x_mes_route_id.operation_ids.filtered(
            lambda op: op.operation_id == operation)

    def _rows(self, serial, operation=False):
        # 夹具只跑本测试建的 SN（跨用例唯一），按 serial 全查即可
        domain = [('serial_identity_id', '=', serial.id)]
        if operation:
            domain.append(('route_operation_id.operation_id', '=', operation.id))
        return self.env['sn.wsd.serial.operation.history'].search(
            domain, order='id asc')

    # ------------------------------------------------------------------
    # 立行与回填
    # ------------------------------------------------------------------

    def test_enter_writes_in_progress_row(self):
        """① 首扫立行：扫码瞬间历史即可见，无需下一站接板。"""
        # spec: station-pass-history/spec/过站扫码即立历史行（在制立行）/投入站首扫立行
        order = self._make_order_online()
        wc = self._make_workcenter(self.op_a)
        serial = order.scan_enter('SN-PHL-001', wc)
        rows = self._rows(serial)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.result, 'in_progress')
        self.assertTrue(rows.in_date)
        self.assertFalse(rows.out_date)
        self.assertFalse(rows.operator_code)
        self.assertEqual(rows.route_operation_id.operation_id, self.op_a)

    def test_next_station_backfills_and_parks(self):
        """② 接板：前站行回填 ok，本站新立在制行。"""
        # spec: station-pass-history/spec/过站扫码即立历史行（在制立行）/中间站接板扫码
        order = self._make_order_online()
        wcs = self._wcs()
        serial = order.scan_enter('SN-PHL-002', wcs['a'])
        row_a_id = self._rows(serial, self.op_a).id
        order.leave_station(serial, 'ok')
        order.scan_enter('SN-PHL-002', wcs['b'])
        row_a = self._rows(serial, self.op_a)
        self.assertEqual(len(row_a), 1)
        self.assertEqual(row_a.id, row_a_id)  # 回填不是新建
        self.assertEqual(row_a.result, 'ok')
        self.assertTrue(row_a.out_date)
        row_b = self._rows(serial, self.op_b)
        self.assertEqual(row_b.result, 'in_progress')
        self.assertFalse(row_b.out_date)

    def test_leave_backfills_same_row_not_create(self):
        """⑤ 防呆锁：出站前后行数不变、行 id 不变。"""
        # spec: station-pass-history/spec/出站回填既有行（不再新建）/接板拉出回填 ok
        order = self._make_order_online()
        wcs = self._wcs()
        serial = order.scan_enter('SN-PHL-003', wcs['a'])
        pending = self._rows(serial)
        self.assertEqual(len(pending), 1)
        order.leave_station(serial, 'ok')
        rows = self._rows(serial)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.id, pending.id)
        self.assertEqual(rows.result, 'ok')

    def test_ng_backfills_defect_on_same_row(self):
        """⑥ NG 两段扫码：缺陷码落回填行，不另起行。"""
        # spec: station-pass-history/spec/出站回填既有行（不再新建）/NG 两段扫码回填
        order = self._make_order_online()
        wcs = self._wcs()
        serial = order.scan_enter('SN-PHL-004', wcs['a'])
        order.leave_station(serial, 'ok')
        serial = order.scan_enter('SN-PHL-004', wcs['b'])
        pending_id = self._rows(serial, self.op_b).id
        order.leave_station(
            serial, 'ng', ng_defect=self.defect_code)
        row = self.env['sn.wsd.serial.operation.history'].browse(pending_id)
        self.assertEqual(row.result, 'ng')
        self.assertEqual(row.defect_code_id, self.defect_code)
        self.assertEqual(self._rows(serial, self.op_b).ids, [pending_id])

    def test_end_operation_backfill_finishes(self):
        """⑦ 尾站确认：回填 ok，流完。"""
        # spec: station-pass-history/spec/出站回填既有行（不再新建）/尾站确认回填
        order = self._make_order_online()
        wcs = self._wcs()
        serial = order.scan_enter('SN-PHL-005', wcs['a'])
        order.leave_station(serial, 'ok')
        serial = order.scan_enter('SN-PHL-005', wcs['b'])
        order.leave_station(serial, 'ok')
        serial = order.scan_enter('SN-PHL-005', wcs['c'])
        finished = order.leave_station(serial, 'ok')
        self.assertTrue(finished)
        self.assertEqual(
            self._rows(serial, self.op_c).result, 'ok')

    def test_scrap_backfills_and_seals(self):
        """⑧ 报废：回填 scrap，SN 封板。报废链需要 BOM 与线边库位。"""
        # spec: station-pass-history/spec/出站回填既有行（不再新建）/报废回填
        self.workshop.component_location_id = self.env['stock.location'].create({
            'name': 'PHL-LINE', 'usage': 'internal',
        })
        component = self.env['product.product'].create({
            'name': 'PHL-COMP', 'uom_id': self.uom_unit.id,
            'is_storable': True,
        })
        product = self.env['product.product'].create({
            'name': 'P-PHL-SCRAP', 'uom_id': self.uom_unit.id,
            'default_code': 'DWG-PHL', 'x_board_side': 'single',
        })
        bom = self.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id,
            'product_id': product.id,
            'product_uom_id': self.uom_unit.id,
            'product_qty': 1.0,
            'type': 'normal',
            'x_workshop_id': self.workshop.id,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id,
                'product_qty': 2.0,
                'product_uom_id': self.uom_unit.id,
            })],
        })
        order = self._make_order_online(product)
        self.assertTrue(order.production_id.bom_id)
        wcs = self._wcs()
        serial = order.scan_enter('SN-PHL-006', wcs['a'])
        order.leave_station(
            serial, 'scrap', scrap_reason=self.scrap_reason)
        self.assertEqual(self._rows(serial, self.op_a).result, 'scrap')
        with self.assertRaises(ValidationError):
            order.scan_enter('SN-PHL-006', wcs['a'])

    def test_retest_legs_coexist(self):
        """⑨ 复测多腿：ng 行保持、新腿独立回填 ok。"""
        # spec: station-pass-history/spec/出站回填既有行（不再新建）/复测多腿共存
        order = self._make_order_online()
        wcs = self._wcs()
        serial = order.scan_enter('SN-PHL-007', wcs['a'])
        order.leave_station(serial, 'ok')
        serial = order.scan_enter('SN-PHL-007', wcs['b'])
        order.leave_station(serial, 'ng', ng_defect=self.defect_code)
        serial = order.scan_enter('SN-PHL-007', wcs['b'])
        self.assertEqual(
            self._rows(serial, self.op_b).mapped('result'),
            ['ng', 'in_progress'])
        order.leave_station(serial, 'ok')
        self.assertEqual(
            self._rows(serial, self.op_b).mapped('result'), ['ng', 'ok'])

    # ------------------------------------------------------------------
    # 完成态语义对在制行不可见
    # ------------------------------------------------------------------

    def test_blocked_enter_writes_no_row(self):
        """④ 进站被拦（质量冻结）不立行。"""
        # spec: station-pass-history/spec/过站扫码即立历史行（在制立行）/进站被拦不立行
        order = self._make_order_online()
        wcs = self._wcs()
        serial = self.env['sn.wsd.serial.identity'].create({
            'name': 'SN-PHL-008', 'company_id': self.company.id,
        })
        self.env['sn.wsd.repair.order'].create({
            'serial_identity_id': serial.id,
            'serial_no': 'SN-PHL-008',
            'mes_order_id': order.id,
            'route_operation_id': self._rop(order, self.op_a).id,
            'defect_code_id': self.defect_code.id,
            'defect_line_ids': [(0, 0, {
                'defect_code_id': self.defect_code.id, 'qty': 1})],
        })
        with self.assertRaises(ValidationError):
            order.scan_enter('SN-PHL-008', wcs['a'])
        self.assertFalse(self._rows(serial))
        self.assertFalse(self.env['sn.wsd.serial.wip'].search(
            [('serial_identity_id', '=', serial.id)]))

    def test_wip_guard_fires_before_cap(self):
        """⑩ 在制腿不占次数：再次进站报"先离站"而非次数上限。"""
        # spec: station-pass-history/spec/完成态语义对在制行不可见/次数上限不计在制腿
        order = self._make_order_online()
        wcs = self._wcs()
        serial = order.scan_enter('SN-PHL-009', wcs['a'])
        order.leave_station(serial, 'ok')
        serial = order.scan_enter('SN-PHL-009', wcs['b'])
        with self.assertRaises(ValidationError) as ctx:
            order.scan_enter('SN-PHL-009', wcs['b'])
        self.assertIn('must leave that station first', str(ctx.exception))

    def test_reachability_ignores_in_progress(self):
        """可达性只认 ok：在制行不解锁后继。"""
        order = self._make_order_online()
        wcs = self._wcs()
        serial = order.scan_enter('SN-PHL-010', wcs['a'])
        reachable = order.get_reachable_operations(serial)
        rop_b = self._rop(order, self.op_b)
        self.assertNotIn(rop_b.id, reachable.ids)

    def test_pending_rows_do_not_count_output(self):
        """⑫ 仅进站在制的板不计产出。"""
        # spec: station-pass-history/spec/完成态语义对在制行不可见/产出与计件口径不变
        order = self._make_order_online()
        wcs = self._wcs()
        order.scan_enter('SN-PHL-011', wcs['a'])
        order.scan_enter('SN-PHL-012', wcs['a'])
        self.assertEqual(order.x_output_qty, 0.0)
        serial = order.scan_enter('SN-PHL-013', wcs['a'])
        order.leave_station(serial, 'ok')
        serial = order.scan_enter('SN-PHL-013', wcs['b'])
        order.leave_station(serial, 'ok')
        self.assertEqual(order.x_output_qty, 1.0)

    # ------------------------------------------------------------------
    # 批次 2：在制查询入口与停留时长
    # ------------------------------------------------------------------

    def test_station_wip_filter_and_ordering(self):
        """⑬⑭ 在制行默认置顶；按单+工序+在制筛出 SN 清单。"""
        # spec: station-pass-history/spec/在制查询入口/按单按工序看在制清单, station-pass-history/spec/在制查询入口/在制徽标与置顶
        order = self._make_order_online()
        wcs = self._wcs()
        serial = order.scan_enter('SN-PHL-020', wcs['a'])
        order.leave_station(serial, 'ok')
        order.scan_enter('SN-PHL-020', wcs['b'])  # A 完成、B 在制
        rows = self.env['sn.wsd.serial.operation.history'].search(
            [('serial_identity_id', '=', serial.id)])
        self.assertEqual(rows[:1].result, 'in_progress')  # NULL 置顶
        wip_rows = self.env['sn.wsd.serial.operation.history'].search([
            ('mes_order_id', '=', order.id),
            ('route_operation_id', '=', self._rop(order, self.op_b).id),
            ('result', '=', 'in_progress'),
        ])
        self.assertEqual(wip_rows.mapped('serial_identity_id'), serial)

    def test_dwell_hours_computed(self):
        """⑮⑯ 已完成行停留时长（存储）；在制行实时已停时长（读时算）。"""
        # spec: station-pass-history/spec/站上停留时长可见/已完成行停留时长, station-pass-history/spec/站上停留时长可见/在制行实时时长
        order = self._make_order_online()
        wcs = self._wcs()
        with freeze_time('2020-03-01 08:00:00'):
            serial = order.scan_enter('SN-PHL-021', wcs['a'])
        with freeze_time('2020-03-01 09:30:00'):
            order.leave_station(serial, 'ok')
        row_a = self._rows(serial, self.op_a)
        self.assertAlmostEqual(row_a.x_dwell_hours, 1.5, places=4)
        self.assertEqual(row_a.x_wip_dwell_hours, 0.0)
        with freeze_time('2020-03-01 10:00:00'):
            order.scan_enter('SN-PHL-021', wcs['b'])
        with freeze_time('2020-03-01 12:00:00'):
            row_b = self._rows(serial, self.op_b)
            self.assertAlmostEqual(row_b.x_wip_dwell_hours, 2.0, places=4)
            self.assertEqual(row_b.x_dwell_hours, 0.0)

    def test_station_wip_action_and_menu(self):
        """「工序在制」动作预置在制过滤与分组，菜单挂追溯下。"""
        # spec: station-pass-history/spec/在制查询入口/按单按工序看在制清单
        action = self.env.ref('sn_wsd_mrp.action_sn_wsd_station_wip')
        self.assertIn('search_default_f_in_progress', action.context)
        menu = self.env.ref('sn_wsd_mrp.menu_sn_wsd_station_wip')
        self.assertEqual(
            menu.parent_id, self.env.ref('sn_wsd_mrp.menu_sn_wsd_traceability'))
        self.assertEqual(menu.name, 'Station WIP')

    # ------------------------------------------------------------------
    # 批次 3：相邻消费方口径回归
    # ------------------------------------------------------------------

    def test_yield_and_pending_list_exclude_in_progress(self):
        """直通率不含在制；仅进站的板不进待维修清单。"""
        # spec: station-pass-history/spec/完成态语义对在制行不可见/产出与计件口径不变
        order = self._make_order_online()
        wcs = self._wcs()
        serial = order.scan_enter('SN-PHL-030', wcs['a'])
        order.leave_station(serial, 'ok')
        serial = order.scan_enter('SN-PHL-030', wcs['b'])
        order.leave_station(serial, 'ng', ng_defect=self.defect_code)
        order.scan_enter('SN-PHL-030', wcs['b'])  # B 在制（未出站）
        rop_b = self._rop(order, self.op_b)
        self.assertEqual(rop_b.x_ok_qty, 0)
        self.assertEqual(rop_b.x_ng_qty, 1)
        self.assertAlmostEqual(rop_b.x_yield_rate, 0.0)
        self.assertFalse(self.env['sn.wsd.repair.pending'].search(
            [('serial_name', '=', 'SN-PHL-030')]))

    def test_clear_pass_counts_in_progress_row(self):
        """清除过站：在制行一并删除并计入审计行数。"""
        # spec: station-pass-history/spec/相邻消费方口径/清除过站含在制行
        order = self._make_order_online()
        wcs = self._wcs()
        serial = order.scan_enter('SN-PHL-031', wcs['a'])
        order.leave_station(serial, 'ok')
        order.scan_enter('SN-PHL-031', wcs['b'])  # B 在制
        cleared = order.action_clear_station_pass(serial)
        self.assertEqual(cleared, 2)  # A ok + B 在制
        self.assertFalse(self._rows(serial))
        self.assertFalse(self.env['sn.wsd.serial.wip'].search(
            [('serial_identity_id', '=', serial.id)]))

    def test_skip_guard_counts_in_progress(self):
        """skip 守卫更严：工序有在制行即算"已执行"，不得跳过。"""
        order = self._make_order_online()
        wcs = self._wcs()
        order.scan_enter('SN-PHL-032', wcs['a'])
        line = self.env['sn.wsd.skip.request.line'].new({
            'route_operation_id': self._rop(order, self.op_a).id,
        })
        self.assertTrue(line._is_route_operation_processed())

    def test_lot_qty_mes_order_excludes_in_progress(self):
        """抽样 mes_order 批量源只数已完成行，AQL 批量不被在制抬高。"""
        # spec: station-pass-history/spec/相邻消费方口径/抽样批量源排除在制
        order = self._make_order_online()
        wcs = self._wcs()
        serial = order.scan_enter('SN-PHL-033', wcs['a'])
        order.leave_station(serial, 'ok')
        order.scan_enter('SN-PHL-033', wcs['b'])  # 在制
        scheme = self.env['sn.wsd.quality.inspection.scheme'].create({
            'name': 'PHL LOT', 'code': 'PHLLOT', 'inspection_type': 'iqc',
            'lot_qty_source': 'mes_order',
        })
        self.assertEqual(
            scheme._get_lot_qty_from_values({'mes_order_id': order.id}), 1)

    # ------------------------------------------------------------------
    # 批次 3（补）：大屏窗口与迁移
    # ------------------------------------------------------------------

    def test_big_screen_window_excludes_in_progress(self):
        """spec: station-pass-history/spec/相邻消费方口径/大屏分析报表窗口不被在制挤占"""
        service = self.env['sn.wsd.mes.dashboard.service']
        before = service.get_big_screen_data()['summary']['today_output_total']
        # 51 块板（1 完成 + 50 在制）超出默认排产，夹具放量避免撞投入上限
        order = self._make_order_online(qty=60)
        wcs = self._wcs()
        serial = order.scan_enter('SN-PHL-036', wcs['a'])
        order.leave_station(serial, 'ok')
        # 50 块在制板塞满 48 行窗口（若未排除会挤掉刚完成的 ok 行）
        for i in range(50):
            order.scan_enter('SN-PHL-FILL-%02d' % i, wcs['a'])
        after = service.get_big_screen_data()['summary']['today_output_total']
        self.assertEqual(after, before + 1)

    def test_upgrade_backfills_pending_rows(self):
        """spec: station-pass-history/spec/存量在制数据迁移/升级补行"""
        import importlib.util
        import os

        from odoo.modules.module import get_module_path
        order = self._make_order_online()
        wcs = self._wcs()
        serial = order.scan_enter('SN-PHL-037', wcs['a'])
        wip = self.env['sn.wsd.serial.wip'].search(
            [('serial_identity_id', '=', serial.id)])
        # 造"升级前在制、无历史行"的形态，再跑迁移函数
        self._rows(serial).unlink()
        path = os.path.join(get_module_path('sn_wsd_mrp'), 'migrations',
                            '19.0.13.0.0', 'post-migrate.py')
        loader_spec = importlib.util.spec_from_file_location(
            'phl_post_migrate', path)
        module = importlib.util.module_from_spec(loader_spec)
        loader_spec.loader.exec_module(module)
        module.migrate(self.env.cr, '19.0.12.0.0')
        rows = self._rows(serial)
        self.assertEqual(rows.result, 'in_progress')
        self.assertEqual(rows.in_date, wip.in_date)
        # 该板后续出站回填此行，不新建
        order.leave_station(serial, 'ok')
        rows = self._rows(serial)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.result, 'ok')

    def test_repair_cutoff_with_in_progress_row(self):
        """⑪ 维修截断 + 在制行（空 out_date）不崩，次数只数截断后。"""
        # spec: station-pass-history/spec/完成态语义对在制行不可见/维修截断遇在制行不崩
        order = self._make_order_online()
        wcs = self._wcs()
        sn = 'SN-PHL-014'
        with freeze_time('2020-02-01 08:00:00', auto_tick_seconds=1):
            self.op_b.x_max_test_count = 2
            serial = order.scan_enter(sn, wcs['a'])
            order.leave_station(serial, 'ok')
            serial = order.scan_enter(sn, wcs['b'])
            order.leave_station(serial, 'ng', ng_defect=self.defect_code)
            serial = order.scan_enter(sn, wcs['b'])
            order.leave_station(serial, 'ng', ng_defect=self.defect_code)
            repair = self.env['sn.wsd.repair.order'].create({
                'serial_identity_id': serial.id,
                'serial_no': sn,
                'mes_order_id': order.id,
                'route_operation_id': self._rop(order, self.op_b).id,
                'repair_entry_route_operation_id':
                    self._rop(order, self.op_b).id,
                'defect_code_id': self.defect_code.id,
                'defect_line_ids': [(0, 0, {
                    'defect_code_id': self.defect_code.id, 'qty': 1})],
            })
            repair.action_report_repair()
            repair.action_start_repair()
            repair.action_repair_ok()
        # 回流重过 B：walked 含截断前的 ng 行，正常进站（真实时钟 > 截断点）
        serial = order.scan_enter(sn, wcs['b'])
        order.leave_station(serial, 'ok')
        # 防御分支：手工留一行无 WIP 的在制行（空 out_date），再进站时
        # 次数过滤不得抛 TypeError，也不得把在制行计入次数
        self.env['sn.wsd.serial.operation.history'].create({
            'serial_identity_id': serial.id,
            'mes_order_id': order.id,
            'route_operation_id': self._rop(order, self.op_b).id,
            'result': 'in_progress',
            'in_date': fields.Datetime.now(),
        })
        serial = order.scan_enter(sn, wcs['b'])
        results = self._rows(serial, self.op_b).mapped('result')
        self.assertEqual(
            results, ['ng', 'ng', 'ok', 'in_progress', 'in_progress'])
