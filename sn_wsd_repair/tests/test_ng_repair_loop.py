from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestNgRepairLoop(TransactionCase):
    """Full NG loop: defect-mandatory NG leave -> re-pass until the retry
    limit -> repair gate -> closed order resets the counter."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create({
            'name': 'WS-NGLOOP', 'code': 'WSNGL'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'NGLOOP', 'code': 'NGL', 'workshop_id': cls.workshop.id,
        })
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True,
        ).create({
            'name': 'RT-NGLOOP', 'code': 'RTNGL',
            'x_workshop_id': cls.workshop.id,
        })
        Operation = cls.env['sn.wsd.operation']
        cls.op_in = Operation.create({
            'name': 'NGLOOP-IN', 'code': 'NGLIN', 'x_station_type': 'assembly'})
        cls.op_out = Operation.create({
            'name': 'NGLOOP-OUT', 'code': 'NGLIN2', 'x_station_type': 'final_test'})
        cls.route.write({
            'state': 'confirmed',
            'x_production_side': 'single',
            'route_operation_ids': [
                (0, 0, {'operation_id': cls.op_in.id, 'sequence': 10}),
                (0, 0, {'operation_id': cls.op_out.id, 'sequence': 20}),
            ],
            'x_daily_input_operation_id': cls.op_in.id,
            'x_daily_output_operation_id': cls.op_out.id,
            'x_workorder_input_operation_id': cls.op_in.id,
        })
        cls.env['sn.wsd.process.route.drawing'].create({
            'route_id': cls.route.id, 'x_drawing_no': 'DWG-NGLOOP',
        })
        route_ops = cls.route.route_operation_ids.sorted('sequence')
        route_ops[0].x_allow_entry = True
        route_ops[1].x_allow_exit = True
        route_ops[1].blocked_by_route_operation_ids = [(6, 0, route_ops[0].ids)]
        cls.defect_code = cls.env['sn.wsd.quality.defect.code'].search(
            [('company_id', 'in', [cls.company.id, False])], limit=1)
        if not cls.defect_code:
            cls.defect_code = cls.env['sn.wsd.quality.defect.code'].create({
                'name': 'NG Loop Defect', 'code': 'NGLD',
                'category': 'other', 'severity': 'minor',
            })

    def _make_order_online(self):
        product = self.env['product.product'].create({
            'name': 'P-NGLOOP', 'uom_id': self.uom_unit.id,
            'default_code': 'DWG-NGLOOP', 'x_board_side': 'single',
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
        return mo, order

    def _make_workcenter(self, operation):
        return self.env['mrp.workcenter'].create({
            'name': 'WC-%s' % operation.code,
            'x_workshop_id': self.workshop.id,
            'x_operation_id': operation.id,
            'x_production_line_id': self.line.id,
        })

    def _ng_pass(self, order, wc, sn_name):
        serial = order.scan_enter(sn_name, wc)
        order.leave_station(serial, 'ng', ng_defect=self.defect_code)
        return serial

    def _history(self, serial, operation):
        return self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id', '=', serial.id),
            ('route_operation_id.operation_id', '=', operation.id),
        ])

    def test_01_ng_requires_defect_and_stamps_it(self):
        mo, order = self._make_order_online()
        wc_in = self._make_workcenter(self.op_in)
        serial = order.scan_enter('SN-LP-001', wc_in)
        with self.assertRaises(ValidationError):
            order.leave_station(serial, 'ng')  # sn_wsd_quality gate
        order.leave_station(serial, 'ng', ng_defect=self.defect_code)
        self.assertEqual(
            self._history(serial, self.op_in).defect_code_id, self.defect_code)

    def test_02_gate_limit_pending_and_reset(self):
        mo, order = self._make_order_online()
        wc_in = self._make_workcenter(self.op_in)
        self.op_in.x_max_test_count = 2
        sn_name = 'SN-LP-002'
        serial = self._ng_pass(order, wc_in, sn_name)
        self._ng_pass(order, wc_in, sn_name)  # limit reached
        # the SN shows up in the pending-repair list
        pending = self.env['sn.wsd.repair.pending'].search(
            [('serial_name', '=', sn_name)])
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending.ng_count, 2)
        self.assertEqual(pending.retry_limit, 2)
        # the retry limit blocks further passes
        with self.assertRaises(ValidationError):
            self._ng_pass(order, wc_in, sn_name)
        # a repair order blocks re-entry until it is closed
        failed_op = self._history(serial, self.op_in)[:1].route_operation_id
        repair_order = self.env['sn.wsd.repair.order'].create({
            'serial_identity_id': serial.id,
            'serial_no': sn_name,
            'mes_order_id': order.id,
            'route_operation_id': failed_op.id,
            'repair_entry_route_operation_id': failed_op.id,
            'defect_code_id': self.defect_code.id,
            'defect_line_ids': [(0, 0, {
                'defect_code_id': self.defect_code.id, 'qty': 1})],
        })
        with self.assertRaises(ValidationError):
            order.scan_enter(sn_name, wc_in)
        # reported repair orders also leave the pending list
        self.assertFalse(self.env['sn.wsd.repair.pending'].search(
            [('serial_name', '=', sn_name)]))
        # close the loop: repair OK resets the retry allowance
        repair_order.action_report_repair()
        repair_order.action_start_repair()
        repair_order.action_repair_ok()
        self.assertEqual(repair_order.state, 'done')
        serial = order.scan_enter(sn_name, wc_in)
        order.leave_station(serial, 'ok')
        results = sorted(self._history(serial, self.op_in).mapped('result'))
        self.assertEqual(results, ['ng', 'ng', 'ok'])

    def test_03_cancelled_repair_does_not_block(self):
        mo, order = self._make_order_online()
        wc_in = self._make_workcenter(self.op_in)
        self.op_in.x_max_test_count = 1
        sn_name = 'SN-LP-003'
        serial = self._ng_pass(order, wc_in, sn_name)
        failed_op = self._history(serial, self.op_in)[:1].route_operation_id
        repair_order = self.env['sn.wsd.repair.order'].create({
            'serial_identity_id': serial.id,
            'serial_no': sn_name,
            'mes_order_id': order.id,
            'route_operation_id': failed_op.id,
            'defect_code_id': self.defect_code.id,
        })
        repair_order.action_cancel()
        # no open order anymore: the retry limit still applies (limit 1)
        with self.assertRaises(ValidationError):
            order.scan_enter(sn_name, wc_in)
        # but with the limit lifted the cancelled order does not block
        self.op_in.x_max_test_count = 0
        order.scan_enter(sn_name, wc_in)

    def test_04_manual_form_prefills_station_ng_defects(self):
        """Scanning the SN on a manually created repair order surfaces the
        station NG defect codes (history), not only open quality issues."""
        mo, order = self._make_order_online()
        wc_in = self._make_workcenter(self.op_in)
        identity = self._ng_pass(order, wc_in, 'SN-LP-004')
        self.assertEqual(
            identity._sn_pending_ng_defect_codes(), self.defect_code)
        new_order = self.env['sn.wsd.repair.order'].new({
            'serial_identity_id': identity.id,
        })
        new_order._onchange_serial_identity_id()
        self.assertIn(
            self.defect_code, new_order.defect_line_ids.mapped('defect_code_id'))

    def test_05_quality_freeze_blocks_entry_and_ok_leave(self):
        """Open quality issue freezes the SN: entry refused, OK leave
        refused, NG leave allowed."""
        mo, order = self._make_order_online()
        wc_in = self._make_workcenter(self.op_in)
        self.op_in.x_max_test_count = 0
        serial = order.scan_enter('SN-LP-005', wc_in)
        self.env['sn.wsd.quality.issue'].create({
            'serial_identity_id': serial.id,
            'defect_code_id': self.defect_code.id,
            'issue_source': 'manual',
        })
        # OK leave refused while frozen
        with self.assertRaises(ValidationError):
            order.leave_station(serial, 'ok')
        # NG leave (offline to repair) stays open
        order.leave_station(serial, 'ng', ng_defect=self.defect_code)
        # re-entry refused while the issue is open
        with self.assertRaises(ValidationError):
            order.scan_enter('SN-LP-005', wc_in)
        # closing the issue unfreezes: re-entry works, counter reset
        self.env['sn.wsd.quality.issue'].search([
            ('serial_identity_id', '=', serial.id)]).write({
            'state': 'closed', 'closed_time': fields.Datetime.now()})
        order.scan_enter('SN-LP-005', wc_in)

    def test_06_binding_registry(self):
        """Product SN and machine SN bind through the binding model."""
        Identity = self.env['sn.wsd.serial.identity']
        product = Identity.get_or_create('SN-BIND-P01', self.company)
        machine = Identity.get_or_create('SN-BIND-M01', self.company)
        self.env['sn.wsd.serial.binding'].create({
            'serial_identity_id': product.id,
            'bound_serial_identity_id': machine.id,
            'binding_type': 'machine',
        })
        self.assertIn(product, machine.bound_machine_binding_ids.mapped('serial_identity_id'))
