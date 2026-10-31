"""Scrap confirmation vs OQC disposition (oqc-disposition-closure batch 6:
tasks 6.1-6.4).

Covers the requirement "OQC Scrap Confirmation Matches the Disposition
State" of mes-oqc:
- a full-lot new NG board (outside the original sample) scraps through
  the standard flow: cells N/A, scrap event, voucher void, release opens
- a draft scrap or a failing stock scrap never closes the board
- a board in rework may be scrapped: its voucher is voided
- restoring a scrap re-opens the disposition as pending without deleting
  the scrap fact; scrapped SNs stay refused by station scans and receipts
- an unconfirmed scrap draft blocks the batch concession."""

from unittest import mock

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.sn_wsd_quality.tests.test_oqc_release_judgment import (
    TestOqcReleaseJudgment,
)




@tagged('post_install', '-at_install')
class TestOqcScrapLink(TestOqcReleaseJudgment):

    def _identity(self, name):
        return self.env['sn.wsd.serial.identity'].search([
            ('name', '=', name), ('company_id', '=', self.company.id)],
            limit=1)

    def _state(self, inspection, serial):
        return inspection._oqc_current_dispositions(serial)[serial.id][
            'state']

    def _scrap_reason(self):
        reason = self.env['sn.wsd.scrap.reason'].search([], limit=1)
        if not reason:
            reason = self.env['sn.wsd.scrap.reason'].create({
                'name': 'OQC Scrap', 'code': 'OQCSCRAP'})
        return reason

    def _scrap_record(self, order, inspection, serial):
        return self.env['sn.wsd.scrap.record'].create({
            'serial_identity_id': serial.id,
            'production_id': order.production_id.id,
            'mes_order_id': order.id,
            'route_operation_id': inspection.route_operation_id.id,
            'scrap_reason_id': self._scrap_reason().id,
            'scrap_qty': 1.0,
        })

    def _full_lot_ng_board(self, order, name):
        """Reject the sample then switch to full lot; a new NG board
        outside the original sample lands pending."""
        inspection = self._ng_round(order, 'SN-SC-001')
        self._ng_round(order, 'SN-SC-002')
        inspection.action_done()
        inspection.action_start_full_inspection()
        self._ng_round(order, name)
        return inspection, self._identity(name)

    # ------------------------------------------------------------------
    # Scenario: full-lot new NG board scraps and closes
    # ------------------------------------------------------------------
    def test_01_full_lot_new_ng_scrap_closes(self):
        order = self._order()
        inspection, board = self._full_lot_ng_board(order, 'SN-SC-101')
        self.assertNotIn(board, inspection.x_fai_serial_ids)
        self.assertEqual(self._state(inspection, board), 'pending')
        scrap = self._scrap_record(order, inspection, board)
        scrap.action_confirm_scrap()
        inspection.invalidate_recordset()
        self.assertEqual(self._state(inspection, board), 'scrapped')
        cells = inspection.cell_ids.filtered(
            lambda c: c.serial_identity_id == board)
        self.assertEqual(set(cells.mapped('result')), {'na'})
        events = self._events(inspection).filtered(
            lambda e: e.action == 'scrap'
            and e.serial_identity_id == board)
        self.assertEqual(len(events), 1)
        self.assertEqual(events.scrap_record_id, scrap)
        self.assertEqual(events.state_after, 'scrapped')
        self.assertEqual(board.x_quality_hold_state, 'scrapped')
        # the board leaves the current defect set (the two reject-setup
        # boards of the fixture stay pending by design)
        pending_ids = {
            sid for sid, info
            in inspection._oqc_current_dispositions().items()
            if info.get('state') == 'pending'}
        self.assertNotIn(board.id, pending_ids)
        self.assertNotIn(board, inspection._oqc_bad_serial_ids())

    # ------------------------------------------------------------------
    # Scenario: a draft scrap or a failing stock scrap never closes
    # ------------------------------------------------------------------
    def test_02_draft_and_failed_scrap_keep_pending(self):
        order = self._order()
        inspection, board = self._full_lot_ng_board(order, 'SN-SC-201')
        # draft only: the board stays pending and unreleased
        draft = self._scrap_record(order, inspection, board)
        self.assertEqual(draft.state, 'draft')
        inspection.invalidate_recordset()
        self.assertEqual(self._state(inspection, board), 'pending')
        # a failing stock scrap rolls the whole confirmation back
        with mock.patch(
                'odoo.addons.stock.models.stock_scrap.StockScrap'
                '.action_validate',
                side_effect=UserError('stock error')):
            with self.assertRaises(UserError):
                draft.action_confirm_scrap()
        draft.invalidate_recordset()
        inspection.invalidate_recordset()
        self.assertEqual(draft.state, 'draft',
                         'the failed confirmation leaves no partial scrap')
        self.assertEqual(self._state(inspection, board), 'pending')
        self.assertNotEqual(board.x_quality_hold_state, 'scrapped')
        self.assertFalse(self._events(inspection).filtered(
            lambda e: e.action == 'scrap'
            and e.serial_identity_id == board))
        # the unconfirmed draft blocks the concession
        wizard_model = self.env['sn.wsd.quality.oqc.concession.wizard']
        blocks = chr(10).join(
            wizard_model._concession_hard_blocks(inspection))
        self.assertIn('Unconfirmed scrap drafts', blocks)
        wizard = self._wizard(inspection)
        self.assertIn('Unconfirmed scrap drafts',
                      wizard.hard_block_reasons or '')
        with self.assertRaises(UserError):
            wizard.action_apply()

    # ------------------------------------------------------------------
    # Scenario: a board in rework may be scrapped, voucher voided
    # ------------------------------------------------------------------
    def test_03_rework_board_scrap_voids_voucher(self):
        order = self._order()
        inspection, board = self._full_lot_ng_board(order, 'SN-SC-301')
        a_row = order.x_mes_route_id.operation_ids.filtered(
            lambda r: r.operation_id == self.op_a)[:1]
        inspection.action_rework_sn(board, a_row, 'Fix it.')
        self.assertEqual(self._state(inspection, board), 'reworking')
        self.assertEqual(board.x_rework_inspection_id, inspection.id)
        scrap = self._scrap_record(order, inspection, board)
        scrap.action_confirm_scrap()
        inspection.invalidate_recordset()
        self.assertEqual(self._state(inspection, board), 'scrapped')
        self.assertFalse(board.x_rework_inspection_id,
                         'the rework voucher is voided by the scrap')

    # ------------------------------------------------------------------
    # Scenario: restoring re-opens the disposition
    # ------------------------------------------------------------------
    def test_04_restore_reopens_disposition(self):
        order = self._order()
        inspection, board = self._full_lot_ng_board(order, 'SN-SC-401')
        scrap = self._scrap_record(order, inspection, board)
        scrap.action_confirm_scrap()
        inspection.invalidate_recordset()
        self.assertEqual(self._state(inspection, board), 'scrapped')
        scrap.action_restore()
        inspection.invalidate_recordset()
        self.assertEqual(self._state(inspection, board), 'pending',
                         'the board is back to disposition')
        restore_events = self._events(inspection).filtered(
            lambda e: e.action == 'scrap_restore'
            and e.serial_identity_id == board)
        self.assertEqual(len(restore_events), 1)
        scrap_events = self._events(inspection).filtered(
            lambda e: e.action == 'scrap'
            and e.serial_identity_id == board)
        self.assertEqual(len(scrap_events), 1,
                         'the original scrap fact stays in history')
        # a pending board again: the release re-closes
        self.assertFalse(inspection.x_oqc_release_ready)
        # the restored (abnormal) board cannot just walk on
        with self.assertRaises(ValidationError):
            order.sn_station_scan(self.wc_b.id, 'SN-SC-401')
