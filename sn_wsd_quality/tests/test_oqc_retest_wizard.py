"""In-place board retest (oqc-disposition-closure batch 4: tasks 4.1-4.4).

Covers the requirement "OQC In-Place Retest with Station-Fact Sync" of
mes-oqc:
- station NG -> retest pass appends a station OK row and unblocks the
  successor operation, the original NG row stays
- manual-cell-only NG (latest pass OK) adds no duplicate station row
- numeric items re-judge on the fresh value; out-of-range stays fail
- duplicate confirmations are refused
- failures roll back atomically (frozen board: nothing moves)
- other boards are untouched by a retest."""

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.sn_wsd_quality.tests.test_oqc_release_judgment import (
    TestOqcReleaseJudgment,
)


@tagged('post_install', '-at_install')
class TestOqcRetestWizard(TestOqcReleaseJudgment):

    def _identity(self, name):
        return self.env['sn.wsd.serial.identity'].search([
            ('name', '=', name), ('company_id', '=', self.company.id)],
            limit=1)

    def _history(self, order, serial):
        return self.env['sn.wsd.serial.operation.history'].search([
            ('mes_order_id', '=', order.id),
            ('serial_identity_id', '=', serial.id),
            ('route_operation_id.operation_id', '=', self.op_c.id),
        ], order='id asc')

    def _wizard(self, inspection, serial, voltage=15.0, visual='pass',
                reason='Retest after repair.', defect=False):
        Wizard = self.env['sn.wsd.quality.oqc.retest.wizard']
        wizard = Wizard.create({
            'inspection_id': inspection.id,
            'serial_identity_id': serial.id,
            'reason': reason,
        })
        wizard._onchange_load_board()
        for row in wizard.line_ids:
            if row.line_id.item_type == 'numeric':
                row.measured_value = voltage
            else:
                row.manual_result = visual
        if defect:
            wizard.defect_code_id = defect.id
        return wizard

    def _state(self, inspection, serial):
        return inspection._oqc_current_dispositions(serial)[serial.id][
            'state']

    # ------------------------------------------------------------------
    # Scenario: station NG -> in-place retest pass -> successor unblocked
    # ------------------------------------------------------------------
    def test_01_station_ng_retest_pass_syncs_history(self):
        order = self._order()
        inspection = self._ng_round(order, 'SN-RT-101')
        board = self._identity('SN-RT-101')
        self.assertEqual(self._state(inspection, board), 'pending')
        self.assertEqual(len(self._history(order, board)), 1)
        self.assertEqual(self._history(order, board).result, 'ng')

        self._wizard(inspection, board).action_apply()

        inspection.invalidate_recordset()
        self.assertEqual(self._state(inspection, board), 'retest_passed')
        history = self._history(order, board)
        self.assertEqual(len(history), 2,
                         'the OK row is appended, the NG row preserved')
        self.assertEqual(history[0].result, 'ng')
        self.assertEqual(history[1].result, 'ok')
        # the board may now enter the successor operation
        res = order.sn_station_scan(self.wc_b.id, 'SN-RT-101')
        if isinstance(res, dict) and res.get('action') == 'leave':
            order.sn_station_leave(res['wip_id'], 'ok')
        b_rows = self.env['sn.wsd.serial.operation.history'].search([
            ('mes_order_id', '=', order.id),
            ('serial_identity_id', '=', board.id),
            ('route_operation_id.operation_id', '=', self.op_b.id)])
        self.assertEqual(len(b_rows), 1)
        self.assertEqual(b_rows.result, 'ok')

    # ------------------------------------------------------------------
    # Scenario: manual-cell-only NG adds no duplicate station row
    # ------------------------------------------------------------------
    def test_02_manual_cell_ng_no_duplicate_station_row(self):
        order = self._order()
        inspection = self._ok_round(order, 'SN-RT-201')
        board = self._identity('SN-RT-201')
        self.assertEqual(len(self._history(order, board)), 1)
        # the inspector fails the board on the cells only
        inspection.cell_ids.filtered(
            lambda c: c.serial_identity_id == board
        ).write({'manual_result': 'fail'})
        self.assertEqual(self._state(inspection, board), 'pending')

        # no defect on the event chain yet: the wizard records it first
        self._wizard(inspection, board, defect=self.defect).action_apply()

        inspection.invalidate_recordset()
        self.assertEqual(self._state(inspection, board), 'retest_passed')
        self.assertEqual(len(self._history(order, board)), 1,
                         'the station OK row is not duplicated')

    # ------------------------------------------------------------------
    # Scenario: numeric items re-judge on the fresh value
    # ------------------------------------------------------------------
    def test_03_numeric_rejudged_on_fresh_value(self):
        order = self._order()
        inspection = self._ng_round(order, 'SN-RT-301')
        board = self._identity('SN-RT-301')
        # out-of-range value keeps the board failed
        self._wizard(inspection, board, voltage=25.0).action_apply()
        inspection.invalidate_recordset()
        self.assertEqual(self._state(inspection, board), 'pending',
                         'an out-of-limit value cannot pass the retest')
        retest_events = self._events(inspection).filtered(
            lambda e: e.action == 'retest'
            and e.serial_identity_id == board)
        self.assertEqual(len(retest_events), 1)
        self.assertIn('Retest failed', retest_events.reason)
        # a fresh in-range value passes on the next confirmation
        self._wizard(inspection, board, voltage=15.0,
                     reason='Second retest after adjustment.').action_apply()
        inspection.invalidate_recordset()
        self.assertEqual(self._state(inspection, board), 'retest_passed')

    # ------------------------------------------------------------------
    # Scenario: duplicate confirmation is refused
    # ------------------------------------------------------------------
    def test_04_duplicate_confirmation_refused(self):
        order = self._order()
        inspection = self._ng_round(order, 'SN-RT-401')
        board = self._identity('SN-RT-401')
        self._wizard(inspection, board).action_apply()
        inspection.invalidate_recordset()
        with self.assertRaises(UserError) as ctx:
            self._wizard(inspection, board,
                         reason='Duplicate submission.').action_apply()
        self.assertIn('currently "retest_passed"', str(ctx.exception))

    # ------------------------------------------------------------------
    # Scenario: failure rolls back atomically
    # ------------------------------------------------------------------
    def test_05_failure_rolls_back_atomically(self):
        order = self._order()
        inspection = self._ng_round(order, 'SN-RT-501')
        board = self._identity('SN-RT-501')
        cells = inspection.cell_ids.filtered(
            lambda c: c.serial_identity_id == board)
        # freeze the board: the retest is refused before anything moves
        self.env['sn.wsd.serial.freeze'].create({
            'serial_identity_id': board.id,
            'freeze_reason': 'Customer hold',
        })
        self.assertEqual(board.x_freeze_state, 'frozen')
        with self.assertRaises(UserError) as ctx:
            self._wizard(inspection, board).action_apply()
        self.assertIn('frozen', str(ctx.exception))
        # nothing moved: cells still failed, no OK station row, still pending
        inspection.invalidate_recordset()
        self.assertTrue(cells.filtered(lambda c: c.result == 'fail'))
        self.assertEqual(len(self._history(order, board)), 1)
        self.assertEqual(self._state(inspection, board), 'pending')

    # ------------------------------------------------------------------
    # Scenario: a retest never touches other boards
    # ------------------------------------------------------------------
    def test_06_retest_does_not_touch_other_boards(self):
        order = self._order()
        inspection = self._ng_round(order, 'SN-RT-601')
        self._ng_round(order, 'SN-RT-602')
        other = self._identity('SN-RT-602')
        self._wizard(inspection, self._identity('SN-RT-601')).action_apply()
        inspection.invalidate_recordset()
        self.assertEqual(
            self._state(inspection, self._identity('SN-RT-601')),
            'retest_passed')
        self.assertEqual(self._state(inspection, other), 'pending')
        other_cells = inspection.cell_ids.filtered(
            lambda c: c.serial_identity_id == other)
        self.assertTrue(other_cells.filtered(lambda c: c.result == 'fail'))
