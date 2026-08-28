from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, freeze_time, tagged


@tagged('post_install', '-at_install')
class TestStationPassCount(TransactionCase):
    """过站总次数口径：OK/NG 各占一次、拦下一次；尾站固定一次；
    OK 不封口；维修关单=截断清零重满 + 回流种子 + 严格可达性；
    待维修清单与产出统计按 SN 去重。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create({
            'name': 'WS-PASSCNT', 'code': 'WSPC'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'PASSCNT', 'code': 'PSC', 'workshop_id': cls.workshop.id,
        })
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-PASSCNT', 'code': 'RTPSC',
                'x_workshop_id': cls.workshop.id,
            })
        Operation = cls.env['sn.wsd.operation']
        cls.op_a = Operation.create({
            'name': 'PC-A', 'code': 'PCA', 'x_station_type': 'assembly',
            'x_max_test_count': 9})
        cls.op_b = Operation.create({
            'name': 'PC-B', 'code': 'PCB', 'x_station_type': 'final_test',
            'x_max_test_count': 3})
        cls.op_c = Operation.create({
            'name': 'PC-C', 'code': 'PCC', 'x_station_type': 'final_test',
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
            # 产出统计挂 B（非尾站、可复过），验证按 SN 去重
            'x_daily_output_operation_id': cls.op_b.id,
            'x_workorder_input_operation_id': cls.op_a.id,
        })
        cls.env['sn.wsd.process.route.drawing'].create({
            'route_id': cls.route.id, 'x_drawing_no': 'DWG-PASSCNT'})
        route_ops = cls.route.route_operation_ids.sorted('sequence')
        route_ops[0].x_allow_entry = True
        route_ops[2].x_allow_exit = True
        route_ops[1].blocked_by_route_operation_ids = [(6, 0, route_ops[0].ids)]
        route_ops[2].blocked_by_route_operation_ids = [(6, 0, route_ops[1].ids)]
        cls.defect_code = cls.env['sn.wsd.quality.defect.code'].search(
            [('company_id', 'in', [cls.company.id, False])], limit=1)
        if not cls.defect_code:
            cls.defect_code = cls.env['sn.wsd.quality.defect.code'].create({
                'name': 'PC Defect', 'code': 'PCD',
                'category': 'other', 'severity': 'minor',
            })

    # ------------------------------------------------------------------
    # fixtures
    # ------------------------------------------------------------------

    def _make_order_online(self):
        product = self.env['product.product'].create({
            'name': 'P-PASSCNT', 'uom_id': self.uom_unit.id,
            'default_code': 'DWG-PASSCNT', 'x_board_side': 'single',
        })
        mo = self.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': 10,
            'company_id': self.company.id,
        })
        order = self.env['sn.wsd.mes.order'].create({
            'production_id': mo.id,
            'production_line_id': self.line.id,
            'date_plan': fields.Date.today(),
            'planned_qty': 4,
        })
        order.action_online()
        return order

    def _make_workcenter(self, operation):
        return self.env['mrp.workcenter'].create({
            'name': 'WC-%s' % operation.code,
            'x_workshop_id': self.workshop.id,
            'x_operation_id': operation.id,
            'x_production_line_id': self.line.id,
        })

    def _pass(self, order, wc, sn_name, result):
        serial = order.scan_enter(sn_name, wc)
        order.leave_station(
            serial, result,
            ng_defect=self.defect_code if result == 'ng' else False)
        return serial

    def _walk_a(self, order, wcs, sn_name):
        self._pass(order, wcs['a'], sn_name, 'ok')

    def _walk_ab(self, order, wcs, sn_name):
        self._pass(order, wcs['a'], sn_name, 'ok')
        self._pass(order, wcs['b'], sn_name, 'ok')

    def _wcs(self):
        return {'a': self._make_workcenter(self.op_a),
                'b': self._make_workcenter(self.op_b),
                'c': self._make_workcenter(self.op_c)}

    def _close_repair(self, serial, sn_name, order, rop, entry_rop):
        repair = self.env['sn.wsd.repair.order'].create({
            'serial_identity_id': serial.id,
            'serial_no': sn_name,
            'mes_order_id': order.id,
            'route_operation_id': rop.id,
            'repair_entry_route_operation_id': entry_rop.id,
            'defect_code_id': self.defect_code.id,
            'defect_line_ids': [(0, 0, {
                'defect_code_id': self.defect_code.id, 'qty': 1})],
        })
        repair.action_report_repair()
        repair.action_start_repair()
        repair.action_repair_ok()
        self.assertEqual(repair.state, 'done')
        return repair

    def _rop(self, order, operation):
        return order.x_mes_route_id.operation_ids.filtered(
            lambda op: op.operation_id == operation)

    def _history(self, serial, operation):
        return self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id', '=', serial.id),
            ('route_operation_id.operation_id', '=', operation.id),
        ])

    # ------------------------------------------------------------------
    # 批1：总次数 + 尾站一次 + OK 不封口 + 必填 ≥1
    # ------------------------------------------------------------------

    def test_cap_counts_ok_and_ng_blocks_fourth(self):
        order = self._make_order_online()
        wcs = self._wcs()
        sn = 'SN-PC-001'
        # B 工序上限 3：walk_ab 的 ok 占 1，ng、ok 再占 2 → 满 3，
        # 第 4 次拦截（拦的是下一次进站）
        # B 工序上限 3：ng+ok+ok 占满 3 次，第 4 次拦截
        self._walk_a(order, wcs, sn)
        self._pass(order, wcs['b'], sn, 'ng')
        self._pass(order, wcs['b'], sn, 'ok')
        self._pass(order, wcs['b'], sn, 'ok')
        with self.assertRaises(ValidationError):
            self._pass(order, wcs['b'], sn, 'ng')

    def test_ok_does_not_seal_mid_operation(self):
        order = self._make_order_online()
        wcs = self._wcs()
        sn = 'SN-PC-002'
        self._walk_a(order, wcs, sn)
        self._pass(order, wcs['b'], sn, 'ok')
        self._pass(order, wcs['b'], sn, 'ok')
        ok_rows = self._history(
            self.env['sn.wsd.serial.identity'].search(
                [('name', '=', sn)]), self.op_b).filtered(
            lambda h: h.result == 'ok')
        self.assertEqual(len(ok_rows), 2)

    def test_exit_operation_capped_at_one_despite_config(self):
        order = self._make_order_online()
        wcs = self._wcs()
        sn = 'SN-PC-003'
        self._walk_ab(order, wcs, sn)
        self._pass(order, wcs['c'], sn, 'ng')
        # 尾站一次机会：即使工序配置 3，第 2 次进站被拦
        with self.assertRaises(ValidationError):
            self._pass(order, wcs['c'], sn, 'ok')

    def test_max_test_count_must_be_at_least_one(self):
        with self.assertRaises(ValidationError):
            self.op_b.x_max_test_count = 0
        self.op_b.x_max_test_count = 3

    # ------------------------------------------------------------------
    # 批2：维修截断（清零重满）+ 回流种子 + 严格可达性
    # ------------------------------------------------------------------

    def test_repair_cutoff_refills_counter(self):
        order = self._make_order_online()
        wcs = self._wcs()
        sn = 'SN-PC-004'
        # 冻结在过去并逐步 tick：过站/关单时间戳严格递增且都早于真实
        # 时钟——退出冻结后写的回流行必然落在截断点之后
        with freeze_time('2020-01-01 08:00:00', auto_tick_seconds=1):
            self.op_b.x_max_test_count = 2
            self._walk_a(order, wcs, sn)
            serial = None
            for _i in range(2):
                serial = self._pass(order, wcs['b'], sn, 'ng')
            with self.assertRaises(ValidationError):
                self._pass(order, wcs['b'], sn, 'ng')
            # 关单=截断：B 计数清零重满
            self._close_repair(
                serial, sn, order, self._rop(order, self.op_b),
                self._rop(order, self.op_b))
        serial = self._pass(order, wcs['b'], sn, 'ok')
        self.assertEqual(
            len(self._history(serial, self.op_b).filtered(
                lambda h: h.result == 'ng')), 2)

    def test_upstream_return_strict_reachability(self):
        order = self._make_order_online()
        wcs = self._wcs()
        sn = 'SN-PC-005'
        with freeze_time('2020-01-01 09:00:00', auto_tick_seconds=1):
            self._walk_ab(order, wcs, sn)
            serial = self._pass(order, wcs['c'], sn, 'ng')
            # C 不良回 B 修：关单后种子=B
            self._close_repair(
                serial, sn, order, self._rop(order, self.op_c),
                self._rop(order, self.op_b))
        # 起点站 A 截断后不再默认可达（未授权）
        with self.assertRaises(ValidationError):
            order.scan_enter(sn, wcs['a'])
        # C 在 B 复过 OK 前不可入
        with self.assertRaises(ValidationError):
            order.scan_enter(sn, wcs['c'])
        # B 授权进站并复过 OK → C 解锁 → 完工（真实时钟 > 冻结的截断点）
        self._pass(order, wcs['b'], sn, 'ok')
        self._pass(order, wcs['c'], sn, 'ok')

    # ------------------------------------------------------------------
    # 批3：待维修清单口径 + 产出统计去重
    # ------------------------------------------------------------------

    def test_pending_list_last_ng_only_and_dedup_stats(self):
        order = self._make_order_online()
        wcs = self._wcs()
        # SN1：3 次用尽且末次 NG → 进清单
        sn1 = 'SN-PC-006'
        self._walk_a(order, wcs, sn1)
        for _i in range(3):
            self._pass(order, wcs['b'], sn1, 'ng')
        pending = self.env['sn.wsd.repair.pending'].search(
            [('serial_name', '=', sn1)])
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending.pass_count, 3)
        self.assertEqual(pending.pass_cap, 3)
        self.assertEqual(pending.last_result, 'ng')
        # SN2：3 次用尽但全 OK → 不进清单
        sn2 = 'SN-PC-007'
        self._walk_a(order, wcs, sn2)
        for _i in range(3):
            self._pass(order, wcs['b'], sn2, 'ok')
        self.assertFalse(self.env['sn.wsd.repair.pending'].search(
            [('serial_name', '=', sn2)]))
        # 产出统计按 SN 去重：B 为产出统计工序，SN2 三行 OK 只算 1 台
        # （不去重会是 3 台；SN1 无 OK 不计）
        self.assertEqual(order.x_output_qty, 1.0)
        rop_b = self._rop(order, self.op_b)
        self.assertEqual(rop_b.x_ok_qty, 1)
        self.assertEqual(rop_b.x_ng_qty, 1)
