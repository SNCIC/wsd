"""OQC batch verdict vs release readiness (oqc-disposition-closure
batch 2, first half: tasks 2.2/2.3).

Covers the non-receipt scenarios of the MODIFIED requirement
"AQL Automatic Verdict and Rejection Linkage" of mes-oqc:
- d <= Ac passes the batch but pending boards keep the release closed
- d >= Re rejects; the document stays dispositionable (reopen service),
  no auto hold / quality issue (regression)
- concession wizard: reason + scope confirmation, stale versions and
  concurrent NG refused
- reopen for disposition keeps the AQL snapshot and re-judges
- one board counted once across NG list / fail cells / defect lines
- concession-accepted boards continue the route, non-conceded do not
- concession never replaces a pending inspection
- the all-pass shortcut is refused while boards await disposition
- an NG after release re-opens the release block
- report mode still creates no OQC document."""

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOqcReleaseJudgment(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create(
            {'name': 'WS-OQCRJ', 'code': 'WSOQCRJ'})
        cls.workshop.component_location_id = cls.env['stock.location'].create(
            {'name': 'LINESIDE-OQCRJ', 'usage': 'internal'}).id
        cls.line = cls.env['sn.mrp.production.line'].create(
            {'name': 'LOQCRJ', 'code': 'LOQCRJ', 'workshop_id': cls.workshop.id})
        Operation = cls.env['sn.wsd.operation']
        cls.op_a = Operation.create({'name': 'OQCRJ-A', 'code': 'OQCRJA'})
        cls.op_c = Operation.create({'name': 'OQCRJ-C', 'code': 'OQCRJC'})
        cls.op_b = Operation.create({'name': 'OQCRJ-B', 'code': 'OQCRJB'})
        # A -> C (OQC, non-tail) -> B: scenario "concession-accepted boards
        # can continue the route" needs a successor operation behind the OQC
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create(
            {'name': 'RT-OQCRJ', 'code': 'RTOQCRJ', 'x_workshop_id': cls.workshop.id})
        cls.route.write({
            'state': 'confirmed', 'x_production_side': 'single',
            'route_operation_ids': [
                (0, 0, {'operation_id': cls.op_a.id, 'sequence': 10,
                        'x_allow_entry': True}),
                (0, 0, {'operation_id': cls.op_c.id, 'sequence': 20}),
                (0, 0, {'operation_id': cls.op_b.id, 'sequence': 30,
                        'x_allow_exit': True}),
            ],
            'x_daily_input_operation_id': cls.op_a.id,
            'x_daily_output_operation_id': cls.op_b.id,
            'x_workorder_input_operation_id': cls.op_a.id,
        })
        ops = cls.route.route_operation_ids.sorted('sequence')
        ops[1].blocked_by_route_operation_ids = [(6, 0, ops[0].ids)]
        ops[2].blocked_by_route_operation_ids = [(6, 0, ops[1].ids)]
        cls.env['sn.wsd.process.route.drawing'].create(
            {'route_id': cls.route.id, 'x_drawing_no': 'DWG-OQCRJ-TEST'})
        cls.product = cls.env['product.product'].create({
            'name': 'P-OQCRJ', 'uom_id': cls.uom_unit.id,
            'default_code': 'DWG-OQCRJ-TEST', 'x_board_side': 'single',
        })
        comp = cls.env['product.product'].create(
            {'name': 'COMP-OQCRJ', 'uom_id': cls.uom_unit.id, 'is_storable': True})
        cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.product.product_tmpl_id.id,
            'product_id': cls.product.id, 'product_uom_id': cls.uom_unit.id,
            'product_qty': 1.0, 'type': 'normal',
            'x_workshop_id': cls.workshop.id,
            'bom_line_ids': [(0, 0, {'product_id': comp.id, 'product_qty': 1.0,
                                      'product_uom_id': cls.uom_unit.id})],
        })
        cls.mo = cls.env['mrp.production'].create({
            'product_id': cls.product.id, 'product_qty': 10,
            'company_id': cls.company.id,
        })
        cls.wc_a = cls.env['mrp.workcenter'].create({
            'name': 'WC-OQCRJ-A', 'x_workshop_id': cls.workshop.id,
            'x_production_line_id': cls.line.id, 'x_operation_id': cls.op_a.id,
        })
        cls.wc_c = cls.env['mrp.workcenter'].create({
            'name': 'WC-OQCRJ-C', 'x_workshop_id': cls.workshop.id,
            'x_production_line_id': cls.line.id, 'x_operation_id': cls.op_c.id,
        })
        cls.wc_b = cls.env['mrp.workcenter'].create({
            'name': 'WC-OQCRJ-B', 'x_workshop_id': cls.workshop.id,
            'x_production_line_id': cls.line.id, 'x_operation_id': cls.op_b.id,
        })
        # n=2, Ac=1, Re=2: one NG board -> pass + pending, two -> reject
        cls.scheme = cls.env['sn.wsd.quality.inspection.scheme'].create({
            'name': 'OQC RJ SCHEME', 'code': 'OQC-RJ-01',
            'inspection_type': 'oqc', 'state': 'effective',
            'operation_id': cls.op_c.id, 'sampling_method': 'fixed',
            'sample_size': 2, 'accept_qty': 1, 'reject_qty': 2,
            'product_tmpl_ids': [(6, 0, cls.product.product_tmpl_id.ids)],
            'line_ids': [
                (0, 0, {'name': 'Voltage', 'item_code': 'OQC-R-VLT',
                        'item_type': 'numeric', 'lower_limit': 10.0,
                        'upper_limit': 20.0}),
                (0, 0, {'name': 'Visual', 'item_code': 'OQC-R-VIS',
                        'item_type': 'pass_fail'}),
            ],
        })
        cls.defect = cls.env['sn.wsd.quality.defect.code'].create({
            'name': 'OQCRJ NG', 'code': 'OQCRJNG',
            'category': 'other', 'severity': 'minor',
        })

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _order(self, mode=False, qty=10, line=False):
        values = {
            'production_id': self.mo.id,
            'production_line_id': (line or self.line).id,
            'date_plan': fields.Date.today(), 'planned_qty': qty,
        }
        if mode:
            values['x_manage_mode'] = mode
        order = self.env['sn.wsd.mes.order'].create(values)
        from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
        gate = give_pick(self.env, order)
        if mode != 'report':
            order.action_online()
            gate.action_cancel()
        return order

    def _pass_op(self, order, wc, name):
        order.sn_station_scan(wc.id, name)
        res = order.sn_station_scan(wc.id, name)
        if isinstance(res, dict) and res.get('action') == 'leave':
            order.sn_station_leave(res['wip_id'], 'ok')

    def _feed_through_a(self, order, name, wc_a=False):
        self._pass_op(order, wc_a or self.wc_a, name)

    def _ok_round(self, order, name, wcs=False):
        """One board walks A OK then leaves the OQC operation OK."""
        wcs = wcs or {'A': self.wc_a, 'C': self.wc_c}
        self._feed_through_a(order, name, wc_a=wcs['A'])
        res = order.sn_station_scan(wcs['C'].id, name)
        if isinstance(res, dict) and res.get('action') == 'leave':
            order.sn_station_leave(res['wip_id'], 'ok')
        return order.x_oqc_inspection_id

    def _ng_round(self, order, name, wcs=False):
        """One board walks A OK then leaves the OQC operation NG: NG list,
        failing cells and a detected event."""
        wcs = wcs or {'A': self.wc_a, 'C': self.wc_c}
        self._feed_through_a(order, name, wc_a=wcs['A'])
        res = order.sn_station_scan(wcs['C'].id, name)
        if isinstance(res, dict) and res.get('action') == 'leave':
            order.sn_station_leave(
                res['wip_id'], 'ng', ng_defect_code_id=self.defect.id)
        return order.x_oqc_inspection_id

    def _alt_line_wcs(self, tag):
        """A second production line with its own work centers: the terminal
        resolves the target order through the scanned work center's line,
        so two live orders in one test must not share work centers."""
        line = self.env['sn.mrp.production.line'].create({
            'name': 'LOQCRJ-%s' % tag, 'code': 'LOQCRJ%s' % tag,
            'workshop_id': self.workshop.id,
        })
        wcs = {}
        for op, key in ((self.op_a, 'A'), (self.op_c, 'C'),
                        (self.op_b, 'B')):
            wcs[key] = self.env['mrp.workcenter'].create({
                'name': 'WC-OQCRJ-%s-%s' % (tag, key),
                'x_workshop_id': self.workshop.id,
                'x_production_line_id': line.id,
                'x_operation_id': op.id,
            })
        return line, wcs

    def _serial(self, name):
        return self.env['sn.wsd.serial.identity'].create({
            'name': name, 'company_id': self.company.id})

    def _oqc_row(self, order):
        return order.x_mes_route_id.operation_ids.filtered(
            lambda r: r.operation_id == self.op_c)[:1]

    def _events(self, inspection):
        return self.env['sn.wsd.quality.oqc.disposition.event'].search([
            ('inspection_id', '=', inspection.id)], order='id asc')

    def _close_retest(self, inspection, serial):
        """Explicit retest confirmation through the private service (the
        batch-3 wizard calls the same entry)."""
        inspection._oqc_append_events([{
            'serial_identity_id': serial.id,
            'action': 'retest',
            'state_before': 'pending',
            'state_after': 'retest_passed',
            'reason': 'Retest confirmed.',
            'defect_code_id': self.defect.id,
            'source_key': 'test-retest-%s-%s' % (inspection.id, serial.id),
        }])

    def _wizard(self, inspection, reason='Customer accepted the defect.'):
        Wizard = self.env['sn.wsd.quality.oqc.concession.wizard']
        defaults = Wizard.with_context(
            default_inspection_id=inspection.id).default_get([
                'company_id', 'inspection_id', 'reason', 'scope_serial_ids',
                'hard_block_reasons', 'expected_versions'])
        return Wizard.create(dict(defaults, reason=reason))

    def _defaults(self, inspection):
        Wizard = self.env['sn.wsd.quality.oqc.concession.wizard']
        return Wizard.with_context(
            default_inspection_id=inspection.id).default_get([
                'company_id', 'inspection_id', 'reason', 'scope_serial_ids',
                'hard_block_reasons', 'expected_versions'])

    # ------------------------------------------------------------------
    # Scenario: d <= Ac passes the batch but pending boards block release
    # ------------------------------------------------------------------
    def test_01_pass_with_pending_board_is_not_released(self):
        order = self._order()
        self._ok_round(order, 'SN-RJ-101')
        insp = self._ng_round(order, 'SN-RJ-102')
        self.assertEqual(len(insp.x_fai_serial_ids), 2)
        self.assertEqual(insp.x_oqc_pending_qty, 1)
        insp.action_done()
        insp.invalidate_recordset()
        self.assertEqual(insp.state, 'done')
        self.assertEqual(insp.result, 'pass',
                         'd = 1 <= Ac = 1 keeps the batch verdict pass')
        self.assertFalse(insp.x_oqc_release_ready,
                         'a pending board keeps the release closed')
        self.assertIn('awaiting disposition', insp.x_oqc_release_message)
        self.assertFalse(insp._oqc_passed())
        self.assertEqual(order.x_oqc_state, 'in_progress')

    # ------------------------------------------------------------------
    # Scenario: d >= Re rejects; no auto hold/issue; reopen stays usable
    # ------------------------------------------------------------------
    def test_02_reject_keeps_disposition_open_without_hold(self):
        order = self._order()
        insp = self._ng_round(order, 'SN-RJ-201')
        self._ng_round(order, 'SN-RJ-202')
        insp.action_done()
        insp.invalidate_recordset()
        self.assertEqual(insp.result, 'reject')
        self.assertFalse(insp.x_oqc_release_ready)
        self.assertIn('verdict', insp.x_oqc_release_message)
        # no auto hold / quality issue: disposition paths stay open
        for name in ('SN-RJ-201', 'SN-RJ-202'):
            serial = self.env['sn.wsd.serial.identity'].search(
                [('name', '=', name)])
            self.assertNotEqual(serial.x_quality_hold_state, 'hold')
        self.assertFalse(self.env['sn.wsd.quality.issue'].search_count([
            ('inspection_id', '=', insp.id)]))
        # the original document is dispositionable: reopen works
        insp._oqc_reopen_for_disposition()
        self.assertEqual(insp.state, 'open')
        self.assertFalse(insp.finish_time)
        self.assertEqual(self._events(insp)[-1].action, 'reopen')

    # ------------------------------------------------------------------
    # Scenario: concession accepts the confirmed scope and closes the batch
    # ------------------------------------------------------------------
    def test_03a_concession_accepts_scope_and_releases(self):
        order = self._order()
        self._ok_round(order, 'SN-RJ-301')
        insp = self._ng_round(order, 'SN-RJ-302')
        insp.action_done()
        insp.invalidate_recordset()
        self.assertEqual(insp.result, 'pass')
        wizard = self._wizard(insp, reason='Cosmetic flaw accepted.')
        self.assertEqual(wizard.scope_serial_ids.mapped('name'),
                         ['SN-RJ-302'])
        self.assertFalse(wizard.hard_block_reasons,
                         'a complete sample with no rework has no blocker')
        wizard.action_apply()
        insp.invalidate_recordset()
        events = self._events(insp)
        concession = events.filtered(
            lambda e: e.action == 'concession'
            and e.serial_identity_id
            and e.serial_identity_id.name == 'SN-RJ-302')
        self.assertEqual(len(concession), 1)
        self.assertEqual(concession.action, 'concession')
        self.assertEqual(concession.state_after, 'concession')
        self.assertEqual(concession.reason, 'Cosmetic flaw accepted.')
        batch = events.filtered(
            lambda e: e.action == 'concession'
            and not e.serial_identity_id)
        self.assertEqual(len(batch), 1)
        self.assertTrue(batch.source_key.startswith(
            'oqc-concession-%s-' % insp.id))
        self.assertEqual(len(batch.after_snapshot['scope']), 1)
        self.assertEqual(batch.after_snapshot['reason'],
                         'Cosmetic flaw accepted.')
        self.assertEqual(insp.result, 'concession')
        self.assertEqual(insp.state, 'done')
        self.assertTrue(insp.x_oqc_release_ready)
        self.assertTrue(insp._oqc_passed())
        self.assertEqual(order.x_oqc_state, 'passed')
        # the NG pass row stays an NG: a concession never fakes a test OK
        history = self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id.name', '=', 'SN-RJ-302'),
            ('route_operation_id', '=', self._oqc_row(order).id)])
        self.assertEqual(set(history.mapped('result')), {'ng'})
        # nothing left to concede: a repeated submit is refused
        with self.assertRaises(UserError) as ctx:
            self._wizard(insp).action_apply()
        self.assertIn('nothing to accept', str(ctx.exception))

    def test_03b_concession_refuses_stale_versions(self):
        order = self._order()
        self._ok_round(order, 'SN-RJ-311')
        insp = self._ng_round(order, 'SN-RJ-312')
        insp.action_done()
        defaults = self._defaults(insp)
        # a concurrent edit bumps the latest event of the scope board
        serial = insp.x_oqc_ng_serial_ids[:1]
        insp._oqc_append_events([{
            'serial_identity_id': serial.id,
            'action': 'result_edit',
            'state_before': 'pending', 'state_after': 'pending',
            'reason': 'Values retyped concurrently.',
            'source_key': 'test-bump-%s' % serial.id,
        }])
        wizard = self.env['sn.wsd.quality.oqc.concession.wizard'].create(
            dict(defaults, reason='Stale confirmation.'))
        with self.assertRaises(UserError) as ctx:
            wizard.action_apply()
        self.assertIn('changed since', str(ctx.exception))
        self.assertEqual(insp.result, 'pass',
                         'the refused apply left the batch untouched')

    def test_03c_concession_refuses_concurrent_new_ng(self):
        order = self._order()
        self._ok_round(order, 'SN-RJ-321')
        insp = self._ng_round(order, 'SN-RJ-322')
        insp.action_done()
        defaults = self._defaults(insp)
        # a new NG lands between opening the wizard and submitting
        ghost = self._serial('SN-RJ-323')
        insp.x_oqc_ng_serial_ids = [(4, ghost.id)]
        wizard = self.env['sn.wsd.quality.oqc.concession.wizard'].create(
            dict(defaults, reason='Scope moved under me.'))
        with self.assertRaises(UserError) as ctx:
            wizard.action_apply()
        self.assertIn('scope changed', str(ctx.exception))

    # ------------------------------------------------------------------
    # Scenario: reopen keeps the AQL snapshot and re-judges on completion
    # ------------------------------------------------------------------
    def test_04_reopen_keeps_aql_snapshot_and_rejudges(self):
        order = self._order()
        insp = self._ng_round(order, 'SN-RJ-401')
        self._ng_round(order, 'SN-RJ-402')
        insp.action_done()
        insp.invalidate_recordset()
        self.assertEqual(insp.result, 'reject')
        insp._oqc_reopen_for_disposition()
        reopen = self._events(insp).filtered(
            lambda e: e.action == 'reopen')
        self.assertEqual(len(reopen), 1)
        self.assertFalse(reopen.serial_identity_id,
                         'the reopen event is batch-level')
        self.assertEqual(reopen.after_snapshot['previous_result'], 'reject')
        self.assertEqual(reopen.after_snapshot['previous_state'], 'done')
        # the frozen AQL snapshot never moves
        self.assertEqual(
            (insp.sample_size, insp.accept_qty, insp.reject_qty),
            (2, 1, 2))
        # disposition closes both boards: d recomputes without a new round
        for name in ('SN-RJ-401', 'SN-RJ-402'):
            self._close_retest(insp, self.env['sn.wsd.serial.identity'].search(
                [('name', '=', name)]))
        insp.invalidate_recordset()
        self.assertEqual(insp.sample_defect_qty, 0,
                         'retest-passed boards leave the current defect set')
        insp.action_done()
        insp.invalidate_recordset()
        self.assertEqual(insp.result, 'pass',
                         're-completion re-judges on the current results')
        self.assertTrue(insp.x_oqc_release_ready)
        self.assertTrue(insp._oqc_passed())

    # ------------------------------------------------------------------
    # Scenario: one board, several defect records, one count
    # ------------------------------------------------------------------
    def test_05_same_board_counted_once(self):
        order = self._order()
        self._ok_round(order, 'SN-RJ-501')
        insp = self._ng_round(order, 'SN-RJ-502')
        serial = insp.x_oqc_ng_serial_ids[:1]
        self.assertEqual(len(insp._oqc_bad_serial_ids()), 1)
        # a defect line carrying the same SN must not add a second count
        self.env['sn.wsd.quality.inspection.defect.line'].create({
            'inspection_id': insp.id,
            'defect_code_id': self.defect.id,
            'serial_identity_id': serial.id,
            'defect_qty': 1,
        })
        insp.invalidate_recordset()
        self.assertEqual(len(insp._oqc_bad_serial_ids()), 1)
        self.assertEqual(insp.sample_defect_qty, 1)
        self.assertEqual(insp.defect_qty, 1)
        # serial-less defect quantities still accumulate on top of d
        self.env['sn.wsd.quality.inspection.defect.line'].create({
            'inspection_id': insp.id,
            'defect_code_id': self.defect.id,
            'defect_qty': 1,
        })
        insp.invalidate_recordset()
        self.assertEqual(insp.defect_qty, 2)

    # ------------------------------------------------------------------
    # Scenario: concession-accepted boards continue the route
    # ------------------------------------------------------------------
    def test_06_concession_board_continues_route(self):
        order = self._order(qty=5)
        self._ok_round(order, 'SN-RJ-601')
        insp = self._ng_round(order, 'SN-RJ-602')
        self._wizard(insp).action_apply()
        order.invalidate_recordset()
        # the conceded board may enter the successor operation B
        order.sn_station_scan(self.wc_b.id, 'SN-RJ-602')
        wip = self.env['sn.wsd.serial.wip'].search([
            ('serial_identity_id.name', '=', 'SN-RJ-602'),
            ('mes_order_id', '=', order.id)])
        self.assertEqual(wip.route_operation_id, self._b_row(order),
                         'the conceded board entered operation B')
        # an unconceded NG board is still refused at B
        line2, wcs2 = self._alt_line_wcs('L2')
        order2 = self._order(qty=5, line=line2)
        self._ok_round(order2, 'SN-RJ-611', wcs=wcs2)
        self._ng_round(order2, 'SN-RJ-612', wcs=wcs2)
        with self.assertRaises(ValidationError) as ctx:
            order2.sn_station_scan(wcs2['B'].id, 'SN-RJ-612')
        self.assertIn('not reachable', str(ctx.exception))

    def _b_row(self, order):
        return order.x_mes_route_id.operation_ids.filtered(
            lambda r: r.operation_id == self.op_b)[:1]

    # ------------------------------------------------------------------
    # Scenario: a concession never replaces a pending inspection
    # ------------------------------------------------------------------
    def test_07a_concession_refused_on_incomplete_sample(self):
        order = self._order()
        insp = self._ng_round(order, 'SN-RJ-701')  # 1 of 2 samples reached
        wizard = self._wizard(insp)
        self.assertIn('incomplete', wizard.hard_block_reasons)
        with self.assertRaises(UserError) as ctx:
            wizard.action_apply()
        self.assertIn('incomplete', str(ctx.exception))
        self.assertNotEqual(insp.result, 'concession')

    def test_07b_concession_refused_on_required_items(self):
        order = self._order()
        self._ok_round(order, 'SN-RJ-711')
        insp = self._ng_round(order, 'SN-RJ-712')
        # blank every cell of both boards: the NG board keeps its pending
        # disposition (its detected event stands) while no fail cell is
        # left, so the required item lines drop back to pending
        insp.cell_ids.write({'manual_result': 'pending',
                             'measured_value': 0.0})
        insp.invalidate_recordset()
        self.assertTrue(insp.line_ids.filtered(
            lambda line: line.required and line.result == 'pending'))
        self.assertEqual(insp.x_oqc_pending_qty, 1,
                         'the NG board still awaits disposition')
        with self.assertRaises(UserError) as ctx:
            self._wizard(insp).action_apply()
        self.assertIn('still pending', str(ctx.exception))

    def test_07c_concession_refused_while_reworking(self):
        order = self._order()
        insp = self._ng_round(order, 'SN-RJ-721')
        serial = insp.x_oqc_ng_serial_ids[:1]
        self._ng_round(order, 'SN-RJ-722')
        op_a_row = order.x_mes_route_id.operation_ids.filtered(
            lambda r: r.operation_id == self.op_a)
        insp.action_rework_sn(serial, op_a_row, 'defect at A')
        with self.assertRaises(UserError) as ctx:
            self._wizard(insp).action_apply()
        self.assertIn('in rework', str(ctx.exception))

    # ------------------------------------------------------------------
    # Scenario: the all-pass shortcut never replaces board confirmation
    # ------------------------------------------------------------------
    def test_08_all_pass_shortcut_refused_with_pending_board(self):
        order = self._order(qty=5)
        self._ok_round(order, 'SN-RJ-801')
        insp = self._ng_round(order, 'SN-RJ-802')
        with self.assertRaises(UserError) as ctx:
            insp.action_set_all_pass()
        self.assertIn('all-pass shortcut', str(ctx.exception))
        with self.assertRaises(UserError):
            insp.action_batch_set_pass()
        # a clean inspection keeps the shortcut
        line2, wcs2 = self._alt_line_wcs('L8')
        order2 = self._order(qty=5, line=line2)
        insp2 = self._ok_round(order2, 'SN-RJ-811', wcs=wcs2)
        self._ok_round(order2, 'SN-RJ-812', wcs=wcs2)
        self.assertTrue(insp2.action_set_all_pass())
        insp2.action_done()
        insp2.invalidate_recordset()
        self.assertEqual(insp2.result, 'pass')
        self.assertTrue(insp2.x_oqc_release_ready)

    # ------------------------------------------------------------------
    # Scenario: an NG after release re-opens the release block
    # ------------------------------------------------------------------
    def test_09_ng_after_release_registers_and_blocks(self):
        order = self._order()
        self._ok_round(order, 'SN-RJ-901')
        insp = self._ok_round(order, 'SN-RJ-902')
        insp.action_done()
        insp.invalidate_recordset()
        self.assertEqual(insp.result, 'pass')
        self.assertTrue(insp.x_oqc_release_ready)
        self.assertTrue(insp._oqc_passed())
        self.assertEqual(order.x_oqc_state, 'passed')
        # a third board leaves the OQC operation NG after the release:
        # the early exit must not swallow it
        self._feed_through_a(order, 'SN-RJ-903')
        res = order.sn_station_scan(self.wc_c.id, 'SN-RJ-903')
        if isinstance(res, dict) and res.get('action') == 'leave':
            order.sn_station_leave(
                res['wip_id'], 'ng', ng_defect_code_id=self.defect.id)
        insp.invalidate_recordset()
        serial = self.env['sn.wsd.serial.identity'].search(
            [('name', '=', 'SN-RJ-903')])
        detected = self._events(insp).filtered(
            lambda e: e.serial_identity_id == serial)
        self.assertEqual(len(detected), 1,
                         'the post-release NG lands a detected event')
        self.assertEqual(detected.action, 'detected')
        self.assertEqual(
            insp._oqc_current_dispositions(serial)[serial.id]['state'],
            'pending')
        self.assertEqual(insp.x_oqc_pending_qty, 1)
        self.assertFalse(insp.x_oqc_release_ready,
                         'the release flips back to blocked')
        self.assertFalse(insp._oqc_passed())
        order.invalidate_recordset()
        self.assertEqual(order.x_oqc_state, 'in_progress')

    # ------------------------------------------------------------------
    # Boundary: report mode still creates no OQC document or verdict
    # ------------------------------------------------------------------
    def test_10_report_mode_creates_no_document(self):
        order = self._order(mode='report')
        a_row = order.x_route_operation_ids.filtered(
            lambda r: r.operation_id == self.op_a)
        c_row = order.x_route_operation_ids.filtered(
            lambda r: r.operation_id == self.op_c)
        order.report_operation_qty(a_row, 2)
        order.report_operation_qty(c_row, 2)
        self.assertFalse(order.x_oqc_inspection_id)
        self.assertEqual(order.x_oqc_state, 'none')
        docs = self.env['sn.wsd.quality.inspection'].search([
            ('mes_order_id', '=', order.id), ('inspection_type', '=', 'oqc')])
        self.assertFalse(docs)
