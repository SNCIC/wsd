"""Full-lot inspection closure (oqc-disposition-closure batch 3:
tasks 3.1-3.4).

Covers the requirement "OQC Full-Lot Abnormal Boards Fully Wired into
Disposition" of mes-oqc:
- a new NG outside the original sample is handled in place (cells,
  pending state) without extending the sample list
- a reworked board coming back OK is not missed by the OK early-exit
- known open boards refuse the full-lot closure, gap confirmation
  included
- inspected 8 of 10: direct completion raises, the gap wizard closes
  with a reason and records the actual quantity
- repeated passes count per board, not per pass."""

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.sn_wsd_quality.tests.test_oqc_release_judgment import (
    TestOqcReleaseJudgment,
)


@tagged('post_install', '-at_install')
class TestOqcFullLotClosure(TestOqcReleaseJudgment):

    def _identity(self, name):
        return self.env['sn.wsd.serial.identity'].search([
            ('name', '=', name), ('company_id', '=', self.company.id)],
            limit=1)

    def _to_full_inspection(self, order, names=('SN-FL-101', 'SN-FL-102')):
        """Two NG boards -> d=2 >= Re=2 -> reject -> full-lot switch."""
        inspection = self._ng_round(order, names[0])
        self._ng_round(order, names[1])
        inspection.action_done()
        inspection.invalidate_recordset()
        self.assertEqual(inspection.result, 'reject')
        inspection.action_start_full_inspection()
        inspection.invalidate_recordset()
        self.assertTrue(inspection.x_full_inspection)
        self.assertEqual(inspection.state, 'open')
        return inspection

    def _repass_ok(self, order, name):
        self._feed_through_a(order, name)
        res = order.sn_station_scan(self.wc_c.id, name)
        if isinstance(res, dict) and res.get('action') == 'leave':
            order.sn_station_leave(res['wip_id'], 'ok')

    def _close_all_retests(self, inspection, names):
        for name in names:
            self._close_retest(inspection, self._identity(name))

    # ------------------------------------------------------------------
    # Scenario: a new NG outside the sample is handled immediately
    # ------------------------------------------------------------------
    def test_01_new_ng_outside_sample_handled_in_place(self):
        order = self._order()
        inspection = self._to_full_inspection(order)
        sample_before = inspection.x_fai_serial_ids
        # a board never in the sample leaves the OQC operation NG
        self._ng_round(order, 'SN-FL-201')
        board = self._identity('SN-FL-201')
        self.assertNotIn(board, inspection.x_fai_serial_ids)
        self.assertEqual(len(inspection.x_fai_serial_ids),
                         len(sample_before),
                         'the sample list is not extended to the lot')
        # abnormal cells + pending disposition exist for it
        cells = inspection.cell_ids.filtered(
            lambda c: c.serial_identity_id == board)
        self.assertTrue(cells)
        self.assertEqual(
            inspection._oqc_current_dispositions(board)[board.id]['state'],
            'pending')
        self.assertIn(board, inspection._oqc_known_serials())

    # ------------------------------------------------------------------
    # Scenario: a reworked board coming back OK is not missed
    # ------------------------------------------------------------------
    def test_02_reworked_board_ok_becomes_awaiting_reinspection(self):
        order = self._order()
        inspection = self._to_full_inspection(order)
        board = self._identity('SN-FL-101')
        # send the NG board back through rework to operation A
        a_op_row = order.x_mes_route_id.operation_ids.filtered(
            lambda r: r.operation_id == self.op_a)[:1]
        inspection.action_rework_sn(board, a_op_row, 'Rework the defect.')
        self.assertEqual(
            inspection._oqc_current_dispositions(board)[board.id]['state'],
            'reworking')
        # the board re-walks A then leaves OQC OK
        self._repass_ok(order, 'SN-FL-101')
        self.assertEqual(
            inspection._oqc_current_dispositions(board)[board.id]['state'],
            'awaiting_reinspection',
            'the OK early-exit must not swallow the reworked board')
        # the closure still refuses while the re-judgment is pending
        with self.assertRaises(UserError) as ctx:
            inspection.with_context(
                sn_wsd_oqc_full_close_reason='gap ok').action_done()
        self.assertIn('not fully disposed', str(ctx.exception))
        # explicit retest confirmation closes it
        self._close_retest(inspection, board)
        self.assertEqual(
            inspection._oqc_current_dispositions(board)[board.id]['state'],
            'retest_passed')

    # ------------------------------------------------------------------
    # Scenario: known open boards refuse the closure, gap or not
    # ------------------------------------------------------------------
    def test_03_open_boards_block_full_close(self):
        order = self._order()
        inspection = self._to_full_inspection(order)
        # SN-FL-101 still pending: even a gap confirmation must not pass
        with self.assertRaises(UserError) as ctx:
            inspection.with_context(
                sn_wsd_oqc_full_close_reason='close anyway').action_done()
        self.assertIn('not fully disposed', str(ctx.exception))

    # ------------------------------------------------------------------
    # Scenario: inspected 8 of 10 -> confirm the gap with a reason
    # ------------------------------------------------------------------
    def test_04_gap_confirmation_records_actual_quantity(self):
        order = self._order()
        inspection = self._to_full_inspection(order)
        # both initial NG boards are disposed (retest) and 6 clean boards
        # pass the operation OK -> inspected 8 of lot 10
        for name in ('SN-FL-101', 'SN-FL-102'):
            self._close_retest(inspection, self._identity(name))
        for index in range(6):
            self._repass_ok(order, 'SN-FL-30%d' % index)
        self.assertEqual(
            len(inspection._oqc_full_inspected_serials()), 8)

        # direct completion raises on the gap, naming both numbers
        with self.assertRaises(UserError) as ctx:
            inspection.action_done()
        self.assertIn('8 of 10', str(ctx.exception))

        # the wizard refuses an empty reason
        Wizard = self.env['sn.wsd.quality.oqc.full.close.wizard']
        wizard = Wizard.create({
            'inspection_id': inspection.id,
            'inspected_qty': 8, 'lot_qty': 10, 'reason': '   ',
        })
        with self.assertRaises(ValidationError):
            wizard.action_apply()

        wizard.reason = 'Two boards were scrapped before inspection.'
        wizard.action_apply()
        inspection.invalidate_recordset()
        self.assertEqual(inspection.state, 'done')
        self.assertTrue(inspection.x_oqc_release_ready)
        # the closure event keeps the actual quantity, not the plan
        close_events = self._events(inspection).filtered(
            lambda e: e.action == 'full_close')
        self.assertEqual(len(close_events), 1)
        self.assertEqual(
            close_events.after_snapshot.get('inspected_qty'), 8)
        self.assertEqual(close_events.after_snapshot.get('gap_qty'), 2)
        self.assertTrue(close_events.reason)

    # ------------------------------------------------------------------
    # Scenario: repeated passes count per board
    # ------------------------------------------------------------------
    def test_05_repeated_passes_count_per_board(self):
        order = self._order()
        inspection = self._to_full_inspection(order)
        board = self._identity('SN-FL-101')
        # NG -> NG -> OK passes of the same board at the inspection
        # operation (cap raised so the repeats are admitted)
        self.op_c.x_max_test_count = 3
        for result, kwargs in (('ng', {'ng_defect_code_id': self.defect.id}),
                               ('ok', {})):
            res = order.sn_station_scan(self.wc_c.id, 'SN-FL-101')
            if isinstance(res, dict) and res.get('action') == 'leave':
                order.sn_station_leave(res['wip_id'], result, **kwargs)
        inspected = inspection._oqc_full_inspected_serials()
        self.assertIn(board, inspected)
        self.assertEqual(
            len(inspected.filtered(lambda s: s == board)), 1,
            'one board counts once regardless of pass count')
        history = self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id', '=', board.id),
            ('mes_order_id', '=', order.id)])
        self.assertGreaterEqual(len(history), 3,
                                'the raw passes stay individually visible')
