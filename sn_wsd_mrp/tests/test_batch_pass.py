from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBatchPass(TransactionCase):
    """批量过站（行政过站）：目标工序完成与上游拉过两条执行路径、
    单事务原子回滚、四禁位、次数上限预检、日志与标记、枚举清理。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create({
            'name': 'WS-BATCHPASS', 'code': 'WSBP'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'BATCHPASS', 'code': 'BPS', 'workshop_id': cls.workshop.id,
        })
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-BATCHPASS', 'code': 'RTBPS',
                'x_workshop_id': cls.workshop.id,
            })
        Operation = cls.env['sn.wsd.operation']
        cls.op_a = Operation.create({
            'name': 'BP-A', 'code': 'BPA',
            'x_max_test_count': 9})
        cls.op_b = Operation.create({
            'name': 'BP-B', 'code': 'BPB',
            'x_max_test_count': 3})
        cls.op_c = Operation.create({
            'name': 'BP-C', 'code': 'BPC',
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
            'x_daily_output_operation_id': cls.op_c.id,
            'x_workorder_input_operation_id': cls.op_a.id,
        })
        cls.env['sn.wsd.process.route.drawing'].create({
            'route_id': cls.route.id, 'x_drawing_no': 'DWG-BATCHPASS'})
        route_ops = cls.route.route_operation_ids.sorted('sequence')
        route_ops[0].x_allow_entry = True
        route_ops[2].x_allow_exit = True
        route_ops[1].blocked_by_route_operation_ids = [(6, 0, route_ops[0].ids)]
        route_ops[2].blocked_by_route_operation_ids = [(6, 0, route_ops[1].ids)]
        cls.defect_code = cls.env['sn.wsd.quality.defect.code'].search(
            [('company_id', 'in', [cls.company.id, False])], limit=1)
        if not cls.defect_code:
            cls.defect_code = cls.env['sn.wsd.quality.defect.code'].create({
                'name': 'BP Defect', 'code': 'BPD',
                'category': 'other', 'severity': 'minor',
            })

    # ------------------------------------------------------------------
    # fixtures
    # ------------------------------------------------------------------

    def _make_order_online(self):
        product = self.env['product.product'].create({
            'name': 'P-BATCHPASS', 'uom_id': self.uom_unit.id,
            'default_code': 'DWG-BATCHPASS', 'x_board_side': 'single',
        })
        mo = self.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': 20,
            'company_id': self.company.id,
        })
        order = self.env['sn.wsd.mes.order'].create({
            'production_id': mo.id,
            'production_line_id': self.line.id,
            'date_plan': fields.Date.today(),
            'planned_qty': 20,
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
        return order.x_route_operation_ids.filtered(
            lambda r: r.operation_id == operation)

    def _pass(self, order, wc, sn_name, result):
        serial = order.scan_enter(sn_name, wc)
        order.leave_station(
            serial, result,
            ng_defect=self.defect_code if result == 'ng' else False)
        return serial

    def _walk_to(self, order, wcs, sn_name, target):
        """Physically pass every operation before ``target`` with OK; the
        board's last record then sits right before the target (strict
        one-scan-per-station keeps no parking rows)."""
        serial = False
        for key in ('a', 'b', 'c'):
            if key == target:
                return serial
            serial = self._pass(order, wcs[key], sn_name, 'ok')
        return serial

    def _batch(self, order, rop, serials, reason='equipment_failure'):
        return order.action_batch_pass_station(
            [s.id for s in serials], rop, reason, note='test')

    def _history(self, serial, order, rop, result):
        return self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id', '=', serial.id),
            ('mes_order_id', '=', order.id),
            ('route_operation_id', '=', rop.id),
            ('result', '=', result),
        ])

    # ------------------------------------------------------------------
    # execution paths
    # ------------------------------------------------------------------

    def test_pass_at_target(self):
        """板停在目标工序前（上一条记录是 A OK）：B 行补 OK 且带标记；
        不做任何停放，C 没有任何记录。"""
        order = self._make_order_online()
        wcs = self._wcs()
        rop_b, rop_c = self._rop(order, self.op_b), self._rop(order, self.op_c)
        serials = [self._walk_to(order, wcs, f'BP-SN-{i}', 'b') for i in range(5)]
        receipt = self._batch(order, rop_b, serials)
        self.assertEqual(receipt['passed'], 5)
        for serial in serials:
            row = self._history(serial, order, rop_b, 'ok')
            self.assertEqual(len(row), 1)
            self.assertTrue(row.x_batch_pass_log_id)
            self.assertFalse(self._history(serial, order, rop_c, 'ok'))
            self.assertFalse(self.env['sn.wsd.serial.wip'].search([
                ('serial_identity_id', '=', serial.id)]))
        log = self.env['sn.wsd.batch.pass.log'].browse(receipt['log_id'])
        self.assertEqual(log.serial_count, 5)
        self.assertEqual(log.reason, 'equipment_failure')
        self.assertEqual(len(log.history_ids), 5)

    def test_no_bridge_over_an_unjudged_operation(self):
        """严格一站一扫：上一条工序还没判定（在制）时，批量过站不得越过
        它替它补 OK——先出站，再行政过下一站。"""
        order = self._make_order_online()
        wcs = self._wcs()
        rop_a, rop_b = self._rop(order, self.op_a), self._rop(order, self.op_b)
        serial = order.scan_enter('BP-UP-1', wcs['a'])  # fed, A unjudged
        reason = order._batch_pass_block_reason(serial, rop_b)
        self.assertTrue(reason)
        self.assertIn('decision pending', reason)
        with self.assertRaises(ValidationError):
            with self.cr.savepoint():
                self._batch(order, rop_b, [serial])
        self.assertFalse(self._history(serial, order, rop_b, 'ok'))
        # the board keeps its own state: still fed at A, nothing else written
        wip = self.env['sn.wsd.serial.wip'].search([
            ('serial_identity_id', '=', serial.id)])
        self.assertEqual(wip.route_operation_id, rop_a)

    def test_atomic_rollback(self):
        """单事务：一台失败整批回滚，无半成品状态、无日志残留。"""
        order = self._make_order_online()
        wcs = self._wcs()
        rop_b = self._rop(order, self.op_b)
        sn_ok = self._walk_to(order, wcs, 'BP-AT-1', 'b')
        sn_far = self._walk_to(order, wcs, 'BP-AT-2', 'c')  # past the target
        with self.assertRaises(ValidationError):
            with self.cr.savepoint():
                self._batch(order, rop_b, [sn_ok, sn_far])
        self.assertEqual(len(self._history(sn_ok, order, rop_b, 'ok')), 0)
        # the first board keeps its A OK and nothing else
        self.assertFalse(self.env['sn.wsd.serial.wip'].search([
            ('serial_identity_id', '=', sn_ok.id)]))
        self.assertFalse(self.env['sn.wsd.batch.pass.log'].search([
            ('mes_order_id', '=', order.id)]), 'no log may survive a rollback')

    # ------------------------------------------------------------------
    # restrictions
    # ------------------------------------------------------------------

    def test_restriction_input_output_material(self):
        order = self._make_order_online()
        rop_a = self._rop(order, self.op_a)
        rop_b = self._rop(order, self.op_b)
        rop_c = self._rop(order, self.op_c)
        serial = order.scan_enter('BP-RX-1', self._make_workcenter(self.op_a))
        with self.assertRaises(ValidationError):
            order._batch_pass_gate_checks(rop_a)
        with self.assertRaises(ValidationError):
            order._batch_pass_gate_checks(rop_c)
        order.x_mes_route_id.x_material_operation_id = rop_b
        with self.assertRaises(ValidationError):
            order._batch_pass_gate_checks(rop_b)
        order.x_mes_route_id.x_material_operation_id = False
        order._batch_pass_gate_checks(rop_b)  # plain mid operation passes

    def test_block_reason_pass_limit(self):
        """次数用尽的板进自动排除清单（预检同源口径）：目标工序的尝试
        额度已用完，板又回到它的前一站。"""
        order = self._make_order_online()
        wcs = self._wcs()
        rop_b = self._rop(order, self.op_b)
        self.op_b.x_max_test_count = 1
        serial = self._walk_to(order, wcs, 'BP-LIM-1', 'b')
        serial = self._pass(order, wcs['b'], 'BP-LIM-1', 'ok')  # cap used up
        # back upstream (repair-style re-entry at the start operation)
        serial = order.scan_enter('BP-LIM-1', wcs['a'])
        order.leave_station(serial, 'ok')
        reason = order._batch_pass_block_reason(serial, rop_b)
        self.assertTrue(reason)
        self.assertIn('pass limit', reason)

    # ------------------------------------------------------------------
    # audit and cleanup
    # ------------------------------------------------------------------

    def test_log_append_only_and_marker_distinguishes(self):
        order = self._make_order_online()
        wcs = self._wcs()
        rop_b = self._rop(order, self.op_b)
        marked = self._walk_to(order, wcs, 'BP-AU-1', 'b')
        self._batch(order, rop_b, [marked], reason='outsourcing')
        log = self.env['sn.wsd.batch.pass.log'].search(
            [('mes_order_id', '=', order.id)])
        self.assertEqual(log.reason, 'outsourcing')
        with self.assertRaises(AccessError):
            log.unlink()
        # a physical pass row stays unmarked and distinguishable
        physical = self._walk_to(order, wcs, 'BP-AU-2', 'b')
        self._pass(order, wcs['b'], 'BP-AU-2', 'ok')
        self.assertFalse(
            self._history(physical, order, rop_b, 'ok').x_batch_pass_log_id)
        self.assertEqual(
            self._history(marked, order, rop_b, 'ok').x_batch_pass_log_id, log)

    def test_skipped_enum_removed(self):
        """sn_wsd_skip 移除后 result 枚举不再含 skipped。"""
        selection = dict(
            self.env['sn.wsd.serial.operation.history']
            ._fields['result'].selection)
        self.assertNotIn('skipped', selection)
