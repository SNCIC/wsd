"""Current-board panel + paginated ledger (oqc-disposition-closure batch 7:
tasks 7.1-7.5, design decision 5).

Covers the ADDED requirement scenarios of inspection-forms:
- OQC current NG-board central disposition: scanning a registered abnormal
  board lands in the panel, illegal SNs (other orders, unregistered
  non-samples) are refused with one message and the current selection is
  kept, the panel buttons prefill retest / rework / scrap
- OQC ledger vs disposition history kept apart: the server-side ledger
  page derives the final verdict per SN (a retested board leaves the NG
  filter, repeated passes count one board, filter matches the counts)
- the scrap entry degrades gracefully when the scrap module is missing
  (env.get branch) and the FAI form keeps its own actions."""

from unittest.mock import patch

from odoo.api import Environment
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.sn_wsd_quality.tests.test_oqc_release_judgment import (
    TestOqcReleaseJudgment,
)


@tagged('post_install', '-at_install')
class TestOqcCurrentPanel(TestOqcReleaseJudgment):

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _identity(self, name):
        return self.env['sn.wsd.serial.identity'].search([
            ('name', '=', name), ('company_id', '=', self.company.id)],
            limit=1)

    def _to_full_inspection(self, order, names=('SN-CP-401', 'SN-CP-402')):
        """Two NG boards -> reject -> full-lot switch (open again)."""
        inspection = self._ng_round(order, names[0])
        self._ng_round(order, names[1])
        inspection.action_done()
        inspection.invalidate_recordset()
        inspection.action_start_full_inspection()
        inspection.invalidate_recordset()
        return inspection

    def _repass_ok(self, order, name):
        self._feed_through_a(order, name)
        res = order.sn_station_scan(self.wc_c.id, name)
        if isinstance(res, dict) and res.get('action') == 'leave':
            order.sn_station_leave(res['wip_id'], 'ok')

    # ------------------------------------------------------------------
    # Scenario: current-board eligibility through the panel service
    # ------------------------------------------------------------------
    def test_01_current_board_info_scope(self):
        Inspection = self.env['sn.wsd.quality.inspection']
        order = self._order(qty=5)
        insp = self._ok_round(order, 'SN-CP-101')
        self._ng_round(order, 'SN-CP-102')
        # a legal board: pending state, chain defect, plain progress info
        info = Inspection.oqc_current_board_info(insp.id, 'SN-CP-102')
        self.assertEqual(info['serial_name'], 'SN-CP-102')
        self.assertEqual(info['state'], 'pending')
        self.assertEqual(info['defect_code_id'], self.defect.id)
        self.assertEqual(info['rework_count'], 0)
        self.assertEqual(info['freeze_state'], 'normal')
        self.assertIn('Awaiting Disposition', info['state_info'])
        # another MES order's board: one refusal message, nothing leaked
        line2, wcs2 = self._alt_line_wcs('C1')
        order2 = self._order(qty=5, line=line2)
        self._ok_round(order2, 'SN-CP-201', wcs=wcs2)
        for name in ('SN-CP-201', 'SN-CP-GHOST'):
            with self.assertRaises(UserError) as ctx:
                Inspection.oqc_current_board_info(insp.id, name)
            self.assertIn('is not part of inspection', str(ctx.exception))
        # an empty scan is its own clear refusal
        with self.assertRaises(UserError) as ctx:
            Inspection.oqc_current_board_info(insp.id, '  ')
        self.assertIn('Scan or pick a board', str(ctx.exception))
        # documents outside the station OQC scope refuse too: a manual
        # document without a MES order, and a nonexistent id
        manual = Inspection.create({
            'inspection_type': 'oqc', 'scheme_id': self.scheme.id})
        with self.assertRaises(UserError):
            Inspection.oqc_current_board_info(manual.id, 'SN-CP-102')
        with self.assertRaises(UserError):
            Inspection.oqc_current_board_info(999999999, 'SN-CP-102')

    # ------------------------------------------------------------------
    # Scenario: scanning a full-lot abnormal board centralizes disposition
    # ------------------------------------------------------------------
    def test_02_scan_registered_abnormal_board_and_refusal_keeps_selection(self):
        order = self._order()
        insp = self._to_full_inspection(order)
        # a board never in the sample leaves the OQC operation NG and scans
        # straight into the panel (no manual sample-list edit)
        self._ng_round(order, 'SN-CP-303')
        self.assertNotIn(self._identity('SN-CP-303'), insp.x_fai_serial_ids)
        insp.x_fai_scan = 'SN-CP-303'
        insp._onchange_x_fai_scan()
        self.assertEqual(insp.x_fai_current_sn.name, 'SN-CP-303')
        self.assertFalse(insp.x_fai_scan, 'the scan box clears itself')
        # the panel fields derive from the latest event
        self.assertEqual(insp.x_oqc_current_state, 'pending')
        self.assertEqual(insp.x_oqc_current_defect_code_id, self.defect)
        self.assertEqual(insp.x_oqc_current_rework_count, 0)
        self.assertEqual(insp.x_oqc_current_freeze_state, 'normal')
        # an illegal scan refuses and keeps the current board untouched
        insp.x_fai_scan = 'SN-CP-GHOST'
        with self.assertRaises(UserError) as ctx:
            insp._onchange_x_fai_scan()
        self.assertIn('is not part of inspection', str(ctx.exception))
        self.assertEqual(insp.x_fai_current_sn.name, 'SN-CP-303',
                         'a refused scan never moves the current board')

    # ------------------------------------------------------------------
    # Scenario: ledger filter matches the displayed final verdict
    # ------------------------------------------------------------------
    def test_03_ledger_page_filters_and_pagination(self):
        Inspection = self.env['sn.wsd.quality.inspection']
        order = self._order()
        insp = self._to_full_inspection(order)
        # close one NG board by retest; six clean boards pass OK
        self._close_retest(insp, self._identity('SN-CP-401'))
        for index in range(6):
            self._repass_ok(order, 'SN-CP-41%d' % index)
        # a repeated pass must not add a ledger row: the pending board
        # leaves the inspection operation a second time (NG then OK rows,
        # one board) -- its disposition stays open until an explicit
        # retest, so the verdict and the counts do not move either
        self.op_c.x_max_test_count = 2
        res = order.sn_station_scan(self.wc_c.id, 'SN-CP-402')
        if isinstance(res, dict) and res.get('action') == 'leave':
            order.sn_station_leave(res['wip_id'], 'ok')
        history = self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id', '=', self._identity('SN-CP-402').id),
            ('mes_order_id', '=', order.id)])
        self.assertGreaterEqual(len(history), 2,
                                'the raw passes stay individually visible')
        ledger = Inspection.oqc_ledger_page(insp.id)
        self.assertEqual(ledger['total'], 8, 'one board counts once per SN')
        self.assertEqual(ledger['counts'], {'ok': 7, 'ng': 1, 'scrap': 0})
        # the NG filter hides the retested board but keeps the pending one
        ng = Inspection.oqc_ledger_page(insp.id, 'ng')
        self.assertEqual(ng['total'], 1)
        self.assertEqual(ng['rows'][0]['serial_name'], 'SN-CP-402')
        self.assertEqual(ng['rows'][0]['verdict'], 'ng')
        self.assertEqual(ng['rows'][0]['disposition_state'], 'pending')
        # the OK filter carries the retested board with its own verdict
        ok = Inspection.oqc_ledger_page(insp.id, 'ok')
        self.assertEqual(ok['total'], 7)
        verdicts = {row['serial_name']: row['verdict'] for row in ok['rows']}
        self.assertEqual(verdicts['SN-CP-401'], 'retested')
        self.assertEqual(verdicts['SN-CP-410'], 'ok')
        # pagination: 8 rows over pages of 3, out-of-range pages clamp
        page2 = Inspection.oqc_ledger_page(insp.id, 'all', 2, 3)
        self.assertEqual(page2['page_count'], 3)
        self.assertEqual(page2['page'], 2)
        self.assertEqual(len(page2['rows']), 3)
        last = Inspection.oqc_ledger_page(insp.id, 'all', 99, 3)
        self.assertEqual(last['page'], 3)
        self.assertEqual(len(last['rows']), 2)
        # SN search narrows the very same criteria
        found = Inspection.oqc_ledger_page(insp.id, 'all', 1, 80,
                                           'SN-CP-40')
        self.assertEqual(
            sorted(row['serial_name'] for row in found['rows']),
            ['SN-CP-401', 'SN-CP-402'])

    # ------------------------------------------------------------------
    # Scenario: panel buttons prefill the wizards; cancel changes nothing
    # ------------------------------------------------------------------
    def test_04_panel_action_buttons_prefill(self):
        order = self._order()
        insp = self._ng_round(order, 'SN-CP-501')
        serial = self._identity('SN-CP-501')
        insp.x_fai_current_sn = serial.id
        retest = insp.action_oqc_retest_current_sn()
        self.assertEqual(retest['res_model'],
                         'sn.wsd.quality.oqc.retest.wizard')
        self.assertEqual(retest['context']['default_serial_identity_id'],
                         serial.id)
        rework = insp.action_oqc_rework_current_sn()
        self.assertEqual(rework['res_model'],
                         'sn.wsd.quality.oqc.rework.wizard')
        self.assertEqual(rework['context']['default_serial_ids'],
                         [(6, 0, serial.ids)])
        scrap = insp.action_oqc_scrap_current_sn()
        self.assertEqual(scrap['res_model'], 'sn.wsd.scrap.record')
        self.assertEqual(scrap['context']['default_serial_identity_id'],
                         serial.id)
        self.assertEqual(scrap['context']['default_mes_order_id'], order.id)
        self.assertEqual(scrap['context']['default_route_operation_id'],
                         insp.route_operation_id.id)
        # opening a wizard and cancelling leaves the business data alone
        events_before = len(self._events(insp))
        self.env['sn.wsd.quality.oqc.retest.wizard'].create({
            'inspection_id': insp.id,
            'serial_identity_id': serial.id,
            'reason': 'opened then cancelled',
        })
        self.assertEqual(len(self._events(insp)), events_before,
                         'a cancelled dialog records no event')
        self.assertEqual(
            insp._oqc_current_dispositions(serial)[serial.id]['state'],
            'pending')
        # without a current board the buttons refuse instead of guessing
        insp.x_fai_current_sn = False
        for method in ('action_oqc_retest_current_sn',
                       'action_oqc_rework_current_sn',
                       'action_oqc_scrap_current_sn'):
            with self.assertRaises(UserError) as ctx:
                getattr(insp, method)()
            self.assertIn('Scan or pick a board', str(ctx.exception))

    # ------------------------------------------------------------------
    # Scenario: the scrap entry degrades when the scrap module is missing
    # ------------------------------------------------------------------
    def test_05_scrap_availability_branch(self):
        order = self._order()
        insp = self._ng_round(order, 'SN-CP-601')
        serial = self._identity('SN-CP-601')
        insp.x_fai_current_sn = serial.id
        # scrap is installed in this database: the entry is live
        self.assertTrue(insp.x_oqc_scrap_available)
        self.assertFalse(insp.x_oqc_scrap_hint)
        # simulate the module being absent: the env.get branch of the
        # compute turns the entry into a hint, never a broken button
        original_get = Environment.get

        def get_without_scrap(env, key, *args, **kwargs):
            if key == 'sn.wsd.scrap.record':
                return None
            return original_get(env, key, *args, **kwargs)

        with patch.object(Environment, 'get', get_without_scrap):
            insp.invalidate_recordset(
                ['x_oqc_scrap_available', 'x_oqc_scrap_hint'])
            self.assertFalse(insp.x_oqc_scrap_available)
            self.assertIn('scrap module', insp.x_oqc_scrap_hint)
            with self.assertRaises(UserError) as ctx:
                insp.action_oqc_scrap_current_sn()
            self.assertIn('scrap module', str(ctx.exception))
            # the retest / rework entries do not depend on scrap
            action = insp.action_oqc_retest_current_sn()
            self.assertEqual(action['res_model'],
                             'sn.wsd.quality.oqc.retest.wizard')

    # ------------------------------------------------------------------
    # Regression: the FAI / IQC / IPQC forms keep their own actions
    # ------------------------------------------------------------------
    def test_06_fai_form_keeps_clear_of_oqc_panel(self):
        # the panel and its stat button carry explicit OQC guards, so the
        # other inspection types never see the disposition actions
        panel_view = self.env.ref(
            'sn_wsd_quality.view_sn_wsd_quality_inspection_form_oqc_panel')
        self.assertIn("inspection_type != 'oqc'", panel_view.arch_db)
        oqc_arch = self.env.ref(
            'sn_wsd_quality.view_sn_wsd_quality_inspection_form_fai').arch_db
        marker = oqc_arch.index('name="oqc_sections"')
        guard = oqc_arch.index('inspection_type', marker)
        self.assertLess(marker, guard,
                        'the OQC sections stay guarded by inspection type')
        for button in ('action_oqc_retest_current_sn',
                       'action_oqc_rework_current_sn',
                       'action_oqc_scrap_current_sn'):
            self.assertIn(button, oqc_arch[marker:])
            self.assertNotIn(button, oqc_arch[:marker],
                             '%s only exists inside the OQC sections'
                             % button)
        # the event history opens server-paginated, scoped to this document
        order = self._order()
        insp = self._ng_round(order, 'SN-CP-701')
        action = insp.action_open_oqc_disposition_events()
        self.assertEqual(action['res_model'],
                         'sn.wsd.quality.oqc.disposition.event')
        self.assertEqual(action['domain'], [('inspection_id', '=', insp.id)])
        self.assertEqual(insp.x_oqc_disposition_event_count, 1)
