from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOqcEntry(TransactionCase):
    """OQC trigger and gate (oqc-entry-trigger): outgoing inspection mirrors
    the FAI state machine — no document on online, the document opens when
    the first board enters the OQC operation (station mode) or on the first
    qualified report (report mode). Lot = order quantity, AQL snapshot
    frozen on the document, entry gated at n samples, NG samples keep their
    slots, Ac/Re verdict drives lock / concession / recheck."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create(
            {'name': 'WS-OQC', 'code': 'WSOQC'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'LOQC', 'code': 'LOQC', 'workshop_id': cls.workshop.id,
        })
        cls.workshop.component_location_id = cls.env['stock.location'].create(
            {'name': 'LINESIDE-OQC', 'usage': 'internal'}).id
        Operation = cls.env['sn.wsd.operation']
        cls.op_in = Operation.create({
            'name': 'OQC-IN', 'code': 'OQIN', 'x_station_type': 'assembly',
            'x_max_test_count': 3,
        })
        cls.op_oqc = Operation.create({
            'name': 'OQC-FINAL', 'code': 'OQFIN', 'x_station_type': 'final_test',
            'x_max_test_count': 3,  # NG boards re-enter after rework
        })
        cls.op_out = Operation.create(
            {'name': 'OQC-OUT', 'code': 'OQOUT', 'x_station_type': 'final_test'})
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-OQC', 'code': 'RTOQC', 'x_workshop_id': cls.workshop.id,
            })
        cls.route.write({
            'state': 'confirmed', 'x_production_side': 'single',
            'route_operation_ids': [
                (0, 0, {'operation_id': cls.op_in.id, 'sequence': 10,
                        'x_allow_entry': True}),
                (0, 0, {'operation_id': cls.op_oqc.id, 'sequence': 20}),
                (0, 0, {'operation_id': cls.op_out.id, 'sequence': 30,
                        'x_allow_exit': True}),
            ],
            'x_daily_input_operation_id': cls.op_in.id,
            'x_daily_output_operation_id': cls.op_out.id,
            'x_workorder_input_operation_id': cls.op_in.id,
        })
        ops = cls.route.route_operation_ids.sorted('sequence')
        ops[1].blocked_by_route_operation_ids = [(6, 0, ops[0].ids)]
        ops[2].blocked_by_route_operation_ids = [(6, 0, ops[1].ids)]
        cls.env['sn.wsd.process.route.drawing'].create(
            {'route_id': cls.route.id, 'x_drawing_no': 'DWG-OQC-TEST'})
        cls.product = cls.env['product.product'].create({
            'name': 'P-OQC', 'uom_id': cls.uom_unit.id,
            'default_code': 'DWG-OQC-TEST', 'x_board_side': 'single',
        })
        component = cls.env['product.product'].create({
            'name': 'COMP-OQC', 'uom_id': cls.uom_unit.id, 'is_storable': True,
        })
        cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.product.product_tmpl_id.id,
            'product_id': cls.product.id,
            'product_uom_id': cls.uom_unit.id, 'product_qty': 1.0,
            'type': 'normal', 'x_workshop_id': cls.workshop.id,
            'bom_line_ids': [(0, 0, {'product_id': component.id,
                                      'product_qty': 2.0,
                                      'product_uom_id': cls.uom_unit.id})],
        })
        cls.mo = cls.env['mrp.production'].create({
            'product_id': cls.product.id, 'product_qty': 10,
            'company_id': cls.company.id,
        })
        cls.wc_in = cls.env['mrp.workcenter'].create({
            'name': 'WC-OQC-IN', 'x_workshop_id': cls.workshop.id,
            'x_production_line_id': cls.line.id,
            'x_operation_id': cls.op_in.id,
        })
        cls.wc_oqc = cls.env['mrp.workcenter'].create({
            'name': 'WC-OQC-FINAL', 'x_workshop_id': cls.workshop.id,
            'x_operation_id': cls.op_oqc.id,
        })
        cls.defect = cls.env['sn.wsd.quality.defect.code'].create({
            'name': 'OQC NG', 'code': 'OQCNG',
            'category': 'other', 'severity': 'minor',
        })
        # compact AQL standard: lot 1-10 -> code A (n=2), lot 11-150 ->
        # code B (n=5); AQL 1.0 normal plans accept 0 / reject 1
        cls.standard = cls.env['sn.wsd.quality.sampling.standard'].create({
            'name': 'OQC TEST STANDARD', 'code': 'STD-OQC-T',
            'lot_range_ids': [
                (0, 0, {'inspection_level': 'g2', 'lot_qty_min': 1,
                        'lot_qty_max': 10, 'sample_size_code': 'A'}),
                (0, 0, {'inspection_level': 'g2', 'lot_qty_min': 11,
                        'lot_qty_max': 150, 'sample_size_code': 'B'}),
            ],
            'plan_ids': [
                (0, 0, {'switching_mode': 'normal', 'sample_size_code': 'A',
                        'sample_size': 2, 'aql_value': 1.0,
                        'accept_qty': 0, 'reject_qty': 1}),
                (0, 0, {'switching_mode': 'normal', 'sample_size_code': 'B',
                        'sample_size': 5, 'aql_value': 1.0,
                        'accept_qty': 0, 'reject_qty': 1}),
            ],
        })
        # OQC scheme on the OQC operation, AQL with lot = MES order quantity
        cls.scheme = cls.env['sn.wsd.quality.inspection.scheme'].create({
            'name': 'OQC SCHEME', 'code': 'OQC-01',
            'inspection_type': 'oqc', 'state': 'effective',
            'operation_id': cls.op_oqc.id,
            'sampling_method': 'aql',
            'sampling_standard_id': cls.standard.id,
            'lot_qty_source': 'mes_order',
            'inspection_level': 'g2',
            'switching_mode': 'normal',
            'aql_value': 1.0,
            'sample_size': 1,  # scheme-level placeholder; AQL decides n
            'product_tmpl_ids': [(6, 0, cls.product.product_tmpl_id.ids)],
            'line_ids': [
                (0, 0, {'name': 'Voltage check', 'item_code': 'OQC-VLT',
                        'item_type': 'numeric', 'lower_limit': 10.0,
                        'upper_limit': 20.0}),
                (0, 0, {'name': 'BOM check', 'item_code': 'OQC-BOM',
                        'item_type': 'text', 'expected_value': 'OK'}),
            ],
        })

    def _order(self, qty=8, mode='station'):
        values = {
            'production_id': self.mo.id, 'production_line_id': self.line.id,
            'date_plan': fields.Date.today(), 'planned_qty': qty,
        }
        if mode != 'station':
            values['x_manage_mode'] = mode
        order = self.env['sn.wsd.mes.order'].create(values)
        # online hard gate (mes-picking-lifecycle): placeholder pick, cancel
        from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
        gate = give_pick(self.env, order)
        order.action_online()
        gate.action_cancel()
        return order

    def _feed(self, order, name):
        return order.scan_enter(name, self.wc_in)

    def _prepare(self, order, name):
        """Feed a board at the start operation and leave it OK, so it is
        ready to enter the OQC operation."""
        serial = self._feed(order, name)
        order.leave_station(serial, 'ok')
        return serial

    def _reach_oqc(self, order, name):
        serial = self._prepare(order, name)
        order.scan_enter(serial.name, self.wc_oqc)
        return serial

    def _oqc_docs(self, order):
        return self.env['sn.wsd.quality.inspection'].search([
            ('inspection_type', '=', 'oqc'),
            ('mes_order_id', '=', order.id),
        ])

    def _op_row(self, order, op):
        return order.x_route_operation_ids.filtered(
            lambda r: r.operation_id == op)[:1]

    def _fixed_scheme(self, sample_size=3, accept=1, reject=2):
        # switch the class scheme to fixed sampling (report-mode tests)
        self.scheme.write({
            'sampling_method': 'fixed', 'sampling_standard_id': False,
            'lot_qty_source': 'manual',
            'sample_size': sample_size, 'accept_qty': accept,
            'reject_qty': reject,
        })

    # ---------------- R1: lazy creation + AQL snapshot ----------------
    def test_10_no_document_before_first_oqc_entry(self):
        # online arms nothing; boards flowing before the OQC operation
        # (feeding + leaving the start operation) create no document
        order = self._order()
        self.assertEqual(order.x_oqc_state, 'none')
        self.assertFalse(order.x_oqc_inspection_id)
        self._prepare(order, 'SN-OQC-001')
        self.assertFalse(self._oqc_docs(order))
        self.assertEqual(order.x_oqc_state, 'none')

    def test_11_first_entry_creates_document_with_aql_snapshot(self):
        # planned 8 -> lot range 1-10 -> code A -> AQL snapshot n=2 Ac=0 Re=1
        order = self._order()
        s1 = self._reach_oqc(order, 'SN-OQC-101')
        inspection = order.x_oqc_inspection_id
        self.assertTrue(inspection)
        self.assertEqual(inspection.inspection_type, 'oqc')
        self.assertEqual(inspection.state, 'open')
        self.assertEqual(inspection.scheme_id, self.scheme)
        self.assertEqual(inspection.mes_order_id, order)
        self.assertEqual(inspection.sampling_method, 'aql')
        self.assertEqual(inspection.sampling_standard_id, self.standard)
        self.assertEqual(inspection.lot_qty, 8,
                         'the lot is the MES order planned quantity')
        self.assertEqual(inspection.sample_size_code, 'A')
        self.assertEqual(inspection.sample_size, 2)
        self.assertEqual(inspection.accept_qty, 0)
        self.assertEqual(inspection.reject_qty, 1)
        self.assertEqual(order.x_oqc_state, 'in_progress')
        self.assertEqual(inspection.x_fai_serial_ids, s1,
                         'the first entered board lands as sample 1')
        # one document per order: the second entry collects, never creates
        s2 = self._reach_oqc(order, 'SN-OQC-102')
        self.assertEqual(inspection.x_fai_serial_ids, s1 | s2)
        self.assertEqual(len(self._oqc_docs(order)), 1)

    # ---------------- R2: entry gate at n samples ----------------
    def test_12_gate_blocks_when_slots_full(self):
        order = self._order()
        s1 = self._reach_oqc(order, 'SN-OQC-201')
        order.leave_station(s1, 'ok')
        s2 = self._reach_oqc(order, 'SN-OQC-202')
        order.leave_station(s2, 'ok')
        inspection = order.x_oqc_inspection_id
        self.assertEqual(len(inspection.x_fai_serial_ids), 2)
        # slots full and not passed: the n+1 board is blocked
        serial3 = self._prepare(order, 'SN-OQC-203')
        with self.assertRaises(ValidationError):
            order.scan_enter(serial3.name, self.wc_oqc)
        # already-registered samples re-enter freely (retest)
        order.scan_enter(s2.name, self.wc_oqc)
        self.assertEqual(len(inspection.x_fai_serial_ids), 2)

    def test_13_ng_leave_keeps_slot_and_counts_to_defects(self):
        # OQC NG samples are NOT dropped (unlike FAI): the slot stays
        # occupied and the board counts to d — refilling would distort AQL
        order = self._order()
        s1 = self._reach_oqc(order, 'SN-OQC-301')
        order.leave_station(s1, 'ng', ng_defect=self.defect)
        inspection = order.x_oqc_inspection_id
        self.assertIn(s1, inspection.x_oqc_ng_serial_ids)
        self.assertIn(s1, inspection.x_fai_serial_ids,
                      'an NG sample keeps its slot')
        self.assertNotIn(s1, inspection.x_fai_arrived_serial_ids)
        self.assertEqual(inspection.defect_qty, 1,
                         'the NG board counts to the defect qty')
        # the slot is not released: board 2 registers, board 3 is blocked
        self._reach_oqc(order, 'SN-OQC-302')
        serial3 = self._prepare(order, 'SN-OQC-303')
        with self.assertRaises(ValidationError):
            order.scan_enter(serial3.name, self.wc_oqc)

    def test_14_ok_leave_arrives_with_default_pass_matrix(self):
        order = self._order()
        s1 = self._reach_oqc(order, 'SN-OQC-401')
        order.leave_station(s1, 'ok')
        inspection = order.x_oqc_inspection_id
        self.assertIn(s1, inspection.x_fai_arrived_serial_ids)
        cells = inspection.cell_ids.filtered(
            lambda c: c.serial_identity_id == s1)
        self.assertEqual(len(cells), 2,
                         'arrival expands one cell per inspection item')
        self.assertEqual(set(cells.mapped('result')), {'pass'},
                         'fresh cells default to pass')
        numeric = cells.filtered(lambda c: c.line_id.item_type == 'numeric')
        self.assertEqual(numeric.measured_value, 15.0,
                         'numeric cells are pre-filled with the midpoint')
        self.assertEqual(set(inspection.line_ids.mapped('result')), {'pass'},
                         'item lines derive pass from the default cells')

    # ---------------- R3: Ac/Re verdict ----------------
    def test_15_done_pass_unlocks_gate(self):
        order = self._order()
        for n in ('SN-OQC-501', 'SN-OQC-502'):
            serial = self._reach_oqc(order, n)
            order.leave_station(serial, 'ok')
        inspection = order.x_oqc_inspection_id
        # default-pass matrix: d = 0 <= Ac = 0
        inspection.action_done()
        inspection.invalidate_recordset()
        self.assertEqual(inspection.state, 'done')
        self.assertEqual(inspection.result, 'pass')
        self.assertEqual(order.x_oqc_state, 'passed')
        # pass releases the whole order: the n+1 board flows in freely
        self._reach_oqc(order, 'SN-OQC-503')
        self.assertEqual(len(self._oqc_docs(order)), 1,
                         'a passed order never grows a second document')

    def test_16_done_reject_locks_holds_no_second_document(self):
        order = self._order()
        s1 = self._reach_oqc(order, 'SN-OQC-601')
        order.leave_station(s1, 'ng', ng_defect=self.defect)
        s2 = self._reach_oqc(order, 'SN-OQC-602')
        order.leave_station(s2, 'ok')
        inspection = order.x_oqc_inspection_id
        # d = 1 NG board >= Re = 1 -> reject
        inspection.action_done()
        inspection.invalidate_recordset()
        self.assertEqual(inspection.state, 'done')
        self.assertEqual(inspection.result, 'reject')
        self.assertNotEqual(order.x_oqc_state, 'passed',
                            'reject keeps the gate armed')
        # bad serial on hold + quality issue to repair
        self.assertEqual(s1.x_quality_hold_state, 'hold')
        issue = self.env['sn.wsd.quality.issue'].search([
            ('inspection_id', '=', inspection.id),
            ('serial_identity_id', '=', s1.id)])
        self.assertEqual(len(issue), 1)
        # no second OQC document (one order, one document, no re-draws)
        self.assertEqual(len(self._oqc_docs(order)), 1)
        # the gate still blocks new boards after the reject
        serial3 = self._prepare(order, 'SN-OQC-603')
        with self.assertRaises(ValidationError):
            order.scan_enter(serial3.name, self.wc_oqc)

    def test_17_concession_unlocks_order(self):
        order = self._order()
        s1 = self._reach_oqc(order, 'SN-OQC-701')
        order.leave_station(s1, 'ng', ng_defect=self.defect)
        s2 = self._reach_oqc(order, 'SN-OQC-702')
        order.leave_station(s2, 'ok')
        inspection = order.x_oqc_inspection_id
        inspection.action_done()
        inspection.invalidate_recordset()
        self.assertEqual(inspection.result, 'reject')
        # disposition decision: concession releases the whole order
        inspection.action_mark_concession()
        inspection.invalidate_recordset()
        self.assertEqual(inspection.result, 'concession')
        self.assertEqual(inspection.state, 'done')
        self.assertEqual(order.x_oqc_state, 'passed',
                         'concession counts as passed')
        self._reach_oqc(order, 'SN-OQC-703')  # gate open

    def test_18_reset_open_recheck_repasses(self):
        # reject driven by a failing cell, then rework: reopen the same
        # document, correct the matrix, judge again on the same snapshot
        order = self._order()
        s1 = self._reach_oqc(order, 'SN-OQC-801')
        order.leave_station(s1, 'ok')
        s2 = self._reach_oqc(order, 'SN-OQC-802')
        order.leave_station(s2, 'ok')
        inspection = order.x_oqc_inspection_id
        cell = inspection.cell_ids.filtered(
            lambda c: c.serial_identity_id == s1
            and c.line_id.item_type == 'numeric')
        cell.write({'measured_value': 25.0})  # over the upper limit
        inspection.action_done()
        inspection.invalidate_recordset()
        self.assertEqual(inspection.result, 'reject')
        self.assertEqual(s1.x_quality_hold_state, 'hold')
        Issue = self.env['sn.wsd.quality.issue']
        self.assertEqual(Issue.search_count(
            [('inspection_id', '=', inspection.id)]), 1)
        # reopen for recheck: the archived matrix stays editable
        inspection.action_reset_open()
        self.assertEqual(inspection.state, 'open')
        self.assertEqual(
            (inspection.sample_size, inspection.accept_qty,
             inspection.reject_qty), (2, 0, 1),
            'recheck re-judges on the same AQL snapshot')
        cell.write({'measured_value': 15.0})  # rework back in range
        inspection.action_done()
        inspection.invalidate_recordset()
        self.assertEqual(inspection.result, 'pass')
        self.assertEqual(order.x_oqc_state, 'passed')
        # no duplicate issue from the second done, and the gate is open
        self.assertEqual(Issue.search_count(
            [('inspection_id', '=', inspection.id)]), 1)
        serial3 = self._prepare(order, 'SN-OQC-803')
        order.scan_enter(serial3.name, self.wc_oqc)

    def test_19_done_guard_needs_full_samples(self):
        order = self._order()
        s1 = self._reach_oqc(order, 'SN-OQC-901')
        order.leave_station(s1, 'ok')
        inspection = order.x_oqc_inspection_id
        # arrived (1) + ng (0) < sample size (2)
        with self.assertRaises(UserError):
            inspection.action_done()

    def test_20_no_scheme_never_triggers(self):
        self.scheme.active = False
        order = self._order()
        for n in ('SN-OQC-NO-1', 'SN-OQC-NO-2', 'SN-OQC-NO-3'):
            serial = self._reach_oqc(order, n)
            order.leave_station(serial, 'ok')
        self.assertFalse(self._oqc_docs(order))
        self.assertEqual(order.x_oqc_state, 'none')

    # ---------------- report mode ----------------
    def test_30_report_mode_first_qualified_report_creates_document(self):
        self._fixed_scheme(sample_size=3, accept=1, reject=2)
        order = self._order(qty=4, mode='report')
        in_row = self._op_row(order, self.op_in)
        oqc_row = self._op_row(order, self.op_oqc)
        order.report_operation_qty(in_row, 4)  # complete the predecessor
        self.assertFalse(order.x_oqc_inspection_id)
        order.report_operation_qty(oqc_row, 2)  # first qualified report
        inspection = order.x_oqc_inspection_id
        self.assertTrue(inspection)
        self.assertEqual(inspection.sampling_method, 'fixed')
        self.assertEqual(inspection.lot_qty, 4,
                         'the lot is the MES order planned quantity')
        self.assertEqual(inspection.sample_size, 3)
        self.assertEqual(inspection.accept_qty, 1)
        self.assertEqual(inspection.reject_qty, 2)
        self.assertEqual(order.x_oqc_state, 'in_progress')
        self.assertEqual(inspection.x_fai_reported_qty, 2.0,
                         'OK qty reported on the OQC operation is drawn')

    def test_31_report_mode_over_quota_blocked_whole_batch(self):
        self._fixed_scheme(sample_size=3, accept=1, reject=2)
        order = self._order(qty=4, mode='report')
        order.report_operation_qty(self._op_row(order, self.op_in), 4)
        oqc_row = self._op_row(order, self.op_oqc)
        with self.assertRaises(ValidationError):
            order.report_operation_qty(oqc_row, 4)  # 4 > n = 3
        order.report_operation_qty(oqc_row, 3)  # exactly the sample size
        inspection = order.x_oqc_inspection_id
        self.assertEqual(inspection.x_fai_reported_qty, 3.0)
        with self.assertRaises(ValidationError):
            order.report_operation_qty(oqc_row, 1)  # over the drawn sample
        self.assertEqual(len(self._oqc_docs(order)), 1)

    def test_32_report_mode_defects_within_accept_pass(self):
        self._fixed_scheme(sample_size=3, accept=1, reject=2)
        order = self._order(qty=4, mode='report')
        order.report_operation_qty(self._op_row(order, self.op_in), 4)
        order.report_operation_qty(self._op_row(order, self.op_oqc), 3)
        inspection = order.x_oqc_inspection_id
        inspection.action_set_all_pass()  # items + drawn samples
        # one defect row of qty 1: d = 1 <= Ac = 1
        inspection.defect_line_ids = [
            (0, 0, {'defect_code_id': self.defect.id, 'defect_qty': 1})]
        inspection.action_done()
        inspection.invalidate_recordset()
        self.assertEqual(inspection.result, 'pass')
        self.assertEqual(order.x_oqc_state, 'passed')

    def test_33_report_mode_defects_over_reject_then_concession(self):
        self._fixed_scheme(sample_size=3, accept=1, reject=2)
        order = self._order(qty=4, mode='report')
        order.report_operation_qty(self._op_row(order, self.op_in), 4)
        order.report_operation_qty(self._op_row(order, self.op_oqc), 3)
        inspection = order.x_oqc_inspection_id
        inspection.action_set_all_pass()
        # defect rows qty drive d: 1 + 1 = 2 >= Re = 2 -> reject
        inspection.defect_line_ids = [
            (0, 0, {'defect_code_id': self.defect.id, 'defect_qty': 1}),
            (0, 0, {'defect_code_id': self.defect.id, 'defect_qty': 1})]
        inspection.action_done()
        inspection.invalidate_recordset()
        self.assertEqual(inspection.result, 'reject')
        self.assertEqual(order.x_oqc_state, 'in_progress')
        # concession is one of the two release paths
        inspection.action_mark_concession()
        inspection.invalidate_recordset()
        self.assertEqual(inspection.result, 'concession')
        self.assertEqual(order.x_oqc_state, 'passed')
