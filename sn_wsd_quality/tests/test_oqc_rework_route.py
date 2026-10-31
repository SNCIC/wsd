"""Rework route scoping and re-inspection closure (oqc-disposition-closure
batch 5: tasks 5.1-5.5).

Covers the requirement "OQC Rework Re-walks the Route and Closes with
Re-inspection" of mes-oqc:
- only graph ancestors of the inspection operation are legal targets
  (the operation itself, downstream ops and unrelated branches refused)
- an old OK cannot skip the re-walk: the strict cutoff admits only OK
  rows newer than the voucher start
- arriving back OK turns awaiting-reinspection; the voucher is kept
  until the explicit retest confirmation clears it
- a repeated NG ends the attempt, back to pending, attempt count kept
- a board with an active WIP cannot be pulled back directly
- a board already received into stock is refused (stock correction)
- reworking boards block release and concession."""

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.sn_wsd_quality.tests.test_oqc_release_judgment import (
    TestOqcReleaseJudgment,
)


@tagged('post_install', '-at_install')
class TestOqcReworkRoute(TestOqcReleaseJudgment):

    def _identity(self, name):
        return self.env['sn.wsd.serial.identity'].search([
            ('name', '=', name), ('company_id', '=', self.company.id)],
            limit=1)

    def _row(self, order, operation):
        return order.x_mes_route_id.operation_ids.filtered(
            lambda r: r.operation_id == operation)[:1]

    def _state(self, inspection, serial):
        return inspection._oqc_current_dispositions(serial)[serial.id][
            'state']

    def _ng_board(self, order, name):
        inspection = self._ng_round(order, name)
        return inspection, self._identity(name)

    def _rework(self, inspection, serial, target_row):
        inspection.action_rework_sn(serial, target_row, 'Fix the defect.')

    def _pass(self, order, name, wc):
        res = order.sn_station_scan(wc.id, name)
        if isinstance(res, dict) and res.get('action') == 'leave':
            order.sn_station_leave(res['wip_id'], 'ok')

    def _retest_pass(self, inspection, serial):
        Wizard = self.env['sn.wsd.quality.oqc.retest.wizard']
        wizard = Wizard.create({
            'inspection_id': inspection.id,
            'serial_identity_id': serial.id,
            'reason': 'Re-inspection passed.',
        })
        wizard._onchange_load_board()
        for row in wizard.line_ids:
            if row.line_id.item_type == 'numeric':
                row.measured_value = 15.0
            else:
                row.manual_result = 'pass'
        wizard.action_apply()

    # ------------------------------------------------------------------
    # Scenario: only upstream ancestors are legal targets
    # ------------------------------------------------------------------
    def test_01_linear_route_legal_and_illegal_targets(self):
        order = self._order()
        inspection, board = self._ng_board(order, 'SN-RW-101')
        candidates = inspection._oqc_rework_target_candidates()
        self.assertEqual(candidates, self._row(order, self.op_a))
        # the inspection operation itself is refused
        with self.assertRaises(ValidationError) as ctx:
            self._rework(inspection, board, self._row(order, self.op_c))
        self.assertIn('not an upstream ancestor', str(ctx.exception))
        # a downstream operation is refused
        with self.assertRaises(ValidationError) as ctx:
            self._rework(inspection, board, self._row(order, self.op_b))
        self.assertIn('not an upstream ancestor', str(ctx.exception))
        # starting rework arms the voucher only: no WIP, no history row
        self._rework(inspection, board, self._row(order, self.op_a))
        self.assertEqual(self._state(inspection, board), 'reworking')
        self.assertFalse(self.env['sn.wsd.serial.wip'].search([
            ('serial_identity_id', '=', board.id)]))
        self.assertEqual(board.x_rework_order_id, order)
        self.assertEqual(board.x_rework_operation_id,
                         self._row(order, self.op_a))
        self.assertTrue(board.x_rework_started_at)

    # ------------------------------------------------------------------
    # Scenario: an old OK cannot skip the re-walk
    # ------------------------------------------------------------------
    def test_02_old_ok_cannot_skip_rewalk(self):
        order = self._order()
        inspection, board = self._ng_board(order, 'SN-RW-201')
        self._rework(inspection, board, self._row(order, self.op_a))
        # the old A OK predates the voucher start: OQC stays unreachable
        with self.assertRaises(ValidationError) as ctx:
            order.sn_station_scan(self.wc_c.id, 'SN-RW-201')
        self.assertIn('not reachable', str(ctx.exception))
        # re-walk the target properly, then OQC admits the board
        self._pass(order, 'SN-RW-201', self.wc_a)
        res = order.sn_station_scan(self.wc_c.id, 'SN-RW-201')
        if isinstance(res, dict) and res.get('action') == 'leave':
            order.sn_station_leave(res['wip_id'], 'ok')
        self.assertEqual(self._state(inspection, board),
                         'awaiting_reinspection')

    # ------------------------------------------------------------------
    # Scenario: the voucher survives until the explicit retest
    # ------------------------------------------------------------------
    def test_03_voucher_kept_until_retest_confirmation(self):
        order = self._order()
        self._ok_round(order, 'SN-RW-302')  # second sample board
        inspection, board = self._ng_board(order, 'SN-RW-301')
        self._rework(inspection, board, self._row(order, self.op_a))
        self._pass(order, 'SN-RW-301', self.wc_a)
        res = order.sn_station_scan(self.wc_c.id, 'SN-RW-301')
        if isinstance(res, dict) and res.get('action') == 'leave':
            order.sn_station_leave(res['wip_id'], 'ok')
        self.assertEqual(self._state(inspection, board),
                         'awaiting_reinspection')
        # the voucher is still armed: only the retest confirmation clears
        self.assertEqual(board.x_rework_inspection_id, inspection.id)
        self.assertFalse(inspection.x_oqc_release_ready)
        self._retest_pass(inspection, board)
        inspection.invalidate_recordset()
        self.assertEqual(self._state(inspection, board), 'retest_passed')
        self.assertFalse(board.x_rework_inspection_id)
        # re-judge the batch and release (verdict vs release are separate)
        inspection.action_done()
        inspection.invalidate_recordset()
        self.assertEqual(inspection.result, 'pass')
        self.assertTrue(inspection.x_oqc_release_ready)

    # ------------------------------------------------------------------
    # Scenario: a repeated NG ends the attempt, count preserved
    # ------------------------------------------------------------------
    def test_04_repeated_ng_back_to_pending(self):
        order = self._order()
        inspection, board = self._ng_board(order, 'SN-RW-401')
        self._rework(inspection, board, self._row(order, self.op_a))
        self._pass(order, 'SN-RW-401', self.wc_a)
        res = order.sn_station_scan(self.wc_c.id, 'SN-RW-401')
        if isinstance(res, dict) and res.get('action') == 'leave':
            order.sn_station_leave(res['wip_id'], 'ng',
                                   ng_defect_code_id=self.defect.id)
        inspection.invalidate_recordset()
        self.assertEqual(self._state(inspection, board), 'pending')
        self.assertEqual(board.x_rework_count, 1,
                         'the attempt count is kept after the failure')
        self.assertFalse(board.x_rework_inspection_id)
        ng_events = self._events(inspection).filtered(
            lambda e: e.action == 'rework_ng'
            and e.serial_identity_id == board)
        self.assertEqual(len(ng_events), 1)
        # the board can start another rework: count goes to 2
        self._rework(inspection, board, self._row(order, self.op_a))
        self.assertEqual(board.x_rework_count, 2)

    # ------------------------------------------------------------------
    # Scenario: an active WIP refuses the direct pull-back
    # ------------------------------------------------------------------
    def test_05_active_wip_refused(self):
        order = self._order()
        inspection, board = self._ng_board(order, 'SN-RW-501')
        # a pending board that still sits in progress at another station
        # (e.g. entered but not judged): rework must refuse the direct
        # pull-back instead of leaving a dangling in-progress row
        self.env['sn.wsd.serial.wip'].sudo().create({
            'serial_identity_id': board.id,
            'mes_order_id': order.id,
            'route_operation_id': self._row(order, self.op_a).id,
        })
        self.assertTrue(self.env['sn.wsd.serial.wip'].search([
            ('serial_identity_id', '=', board.id)]))
        with self.assertRaises(ValidationError) as ctx:
            self._rework(inspection, board, self._row(order, self.op_a))
        self.assertIn('still in progress', str(ctx.exception))
        # no dangling row was fabricated nor removed by the refusal
        self.assertTrue(self.env['sn.wsd.serial.wip'].search([
            ('serial_identity_id', '=', board.id)]))

    # ------------------------------------------------------------------
    # Scenario: a received board is refused (stock correction path)
    # ------------------------------------------------------------------
    def test_06_already_received_refused(self):
        order = self._order()
        inspection, board = self._ng_board(order, 'SN-RW-601')
        carton = self.env['stock.package'].get_or_create_wsd_package(
            'CTN-RW-01', 'carton', self.company)
        self.env['sn.wsd.meter.pack.record'].create({
            'serial_identity_id': board.id,
            'production_id': order.production_id.id,
            'carton_package_id': carton.id,
        })
        BindLog = self.env['sn.wsd.carton.pallet.binding.log']
        BindLog.bind_carton_to_pallet('PLT-RW-01', 'CTN-RW-01')
        pallet = self.env['stock.package'].search([
            ('name', '=', 'PLT-RW-01'),
            ('x_wsd_package_role', '=', 'pallet')], limit=1)
        # mimic the post-receipt reality of the pallet
        pallet.x_wsd_pack_state = 'received'
        with self.assertRaises(ValidationError) as ctx:
            self._rework(inspection, board, self._row(order, self.op_a))
        self.assertIn('already been received', str(ctx.exception))

    # ------------------------------------------------------------------
    # Scenario: reworking boards block release and concession
    # ------------------------------------------------------------------
    def test_07_reworking_blocks_release_and_concession(self):
        order = self._order()
        inspection = self._ok_round(order, 'SN-RW-701')
        inspection, board = self._ng_board(order, 'SN-RW-702')
        self._rework(inspection, board, self._row(order, self.op_a))
        inspection.action_done()
        inspection.invalidate_recordset()
        self.assertEqual(inspection.result, 'pass')  # d=1 <= Ac=1
        self.assertFalse(inspection.x_oqc_release_ready)
        wizard = self._wizard(inspection)
        with self.assertRaises(UserError) as ctx:
            wizard.action_apply()
        self.assertIn('rework', str(ctx.exception).lower())
