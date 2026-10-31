"""OQC disposition audit events (oqc-disposition-closure batch 1).

Covers the ADDED requirement scenarios of mes-oqc:
- OQC Disposition Status and Release Scope per Board (manual cell NG /
  device NG both land a detected event, missing cells stay pending,
  closed boards re-open on a new NG, raw device defect codes register
  but never close, freezes keep blocking)
- OQC Disposition Audit History Cannot Be Overwritten (RPC tampering
  and cross-company reads refused, stale versions and duplicate source
  keys rejected, upgrade baseline built from visible evidence only,
  parent deletion blocked by the restrict foreign key)."""

from psycopg2 import IntegrityError

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOqcDispositionEvents(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create(
            {'name': 'WS-OQCEV', 'code': 'WSOQCEV'})
        cls.workshop.component_location_id = cls.env['stock.location'].create(
            {'name': 'LINESIDE-OQCEV', 'usage': 'internal'}).id
        cls.line = cls.env['sn.mrp.production.line'].create(
            {'name': 'LOQCEV', 'code': 'LOQCEV', 'workshop_id': cls.workshop.id})
        Operation = cls.env['sn.wsd.operation']
        cls.op_a = Operation.create({'name': 'OQCEV-A', 'code': 'OQCEVA'})
        cls.op_c = Operation.create({'name': 'OQCEV-C', 'code': 'OQCEVC'})
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create(
            {'name': 'RT-OQCEV', 'code': 'RTOQCEV', 'x_workshop_id': cls.workshop.id})
        cls.route.write({
            'state': 'confirmed', 'x_production_side': 'single',
            'route_operation_ids': [
                (0, 0, {'operation_id': cls.op_a.id, 'sequence': 10,
                        'x_allow_entry': True}),
                (0, 0, {'operation_id': cls.op_c.id, 'sequence': 20,
                        'x_allow_exit': True}),
            ],
            'x_daily_input_operation_id': cls.op_a.id,
            'x_daily_output_operation_id': cls.op_c.id,
            'x_workorder_input_operation_id': cls.op_a.id,
        })
        ops = cls.route.route_operation_ids.sorted('sequence')
        ops[1].blocked_by_route_operation_ids = [(6, 0, ops[0].ids)]
        cls.env['sn.wsd.process.route.drawing'].create(
            {'route_id': cls.route.id, 'x_drawing_no': 'DWG-OQCEV-TEST'})
        cls.product = cls.env['product.product'].create({
            'name': 'P-OQCEV', 'uom_id': cls.uom_unit.id,
            'default_code': 'DWG-OQCEV-TEST', 'x_board_side': 'single',
        })
        comp = cls.env['product.product'].create(
            {'name': 'COMP-OQCEV', 'uom_id': cls.uom_unit.id, 'is_storable': True})
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
            'name': 'WC-OQCEV-A', 'x_workshop_id': cls.workshop.id,
            'x_production_line_id': cls.line.id, 'x_operation_id': cls.op_a.id,
        })
        cls.wc_c = cls.env['mrp.workcenter'].create({
            'name': 'WC-OQCEV-C', 'x_workshop_id': cls.workshop.id,
            'x_production_line_id': cls.line.id, 'x_operation_id': cls.op_c.id,
        })
        # numeric + text + pass_fail items so cell edits have real values
        cls.scheme = cls.env['sn.wsd.quality.inspection.scheme'].create({
            'name': 'OQC EV SCHEME', 'code': 'OQC-EV-01',
            'inspection_type': 'oqc', 'state': 'effective',
            'operation_id': cls.op_c.id, 'sampling_method': 'fixed',
            'sample_size': 1,
            'product_tmpl_ids': [(6, 0, cls.product.product_tmpl_id.ids)],
            'line_ids': [
                (0, 0, {'name': 'Voltage', 'item_code': 'OQC-E-VLT',
                        'item_type': 'numeric', 'lower_limit': 10.0,
                        'upper_limit': 20.0}),
                (0, 0, {'name': 'BOM check', 'item_code': 'OQC-E-BOM',
                        'item_type': 'text', 'expected_value': 'OK'}),
                (0, 0, {'name': 'Visual', 'item_code': 'OQC-E-VIS',
                        'item_type': 'pass_fail'}),
            ],
        })
        cls.defect = cls.env['sn.wsd.quality.defect.code'].create({
            'name': 'OQCEV NG', 'code': 'OQCEVNG',
            'category': 'other', 'severity': 'minor',
        })

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _order(self):
        order = self.env['sn.wsd.mes.order'].create({
            'production_id': self.mo.id, 'production_line_id': self.line.id,
            'date_plan': fields.Date.today(), 'planned_qty': 10,
        })
        from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
        gate = give_pick(self.env, order)
        order.action_online()
        gate.action_cancel()
        return order

    def _feed_through_a(self, order, name):
        order.sn_station_scan(self.wc_a.id, name)
        res = order.sn_station_scan(self.wc_a.id, name)
        if isinstance(res, dict) and res.get('action') == 'leave':
            order.sn_station_leave(res['wip_id'], 'ok')

    def _ok_round(self, order, name):
        """Feed one board, pass op A OK, then leave op C OK: it arrives as
        a sample with the default pass matrix."""
        self._feed_through_a(order, name)
        res = order.sn_station_scan(self.wc_c.id, name)
        if isinstance(res, dict) and res.get('action') == 'leave':
            order.sn_station_leave(res['wip_id'], 'ok')
        return order.x_oqc_inspection_id

    def _ng_round(self, order, name):
        """Feed one board, pass op A OK, then leave op C with NG: the board
        lands on the NG list with failing cells and a detected event."""
        self._feed_through_a(order, name)
        res = order.sn_station_scan(self.wc_c.id, name)
        if isinstance(res, dict) and res.get('action') == 'leave':
            order.sn_station_leave(
                res['wip_id'], 'ng', ng_defect_code_id=self.defect.id)
        return order.x_oqc_inspection_id

    def _serial(self, name):
        return self.env['sn.wsd.serial.identity'].create({
            'name': name, 'company_id': self.company.id})

    def _oqc_row(self, order):
        return order.x_mes_route_id.operation_ids.filtered(
            lambda r: r.operation_id == self.op_c)[:1]

    def _events(self, inspection):
        return self.env['sn.wsd.quality.oqc.disposition.event'].search([
            ('inspection_id', '=', inspection.id)], order='id asc')

    # ------------------------------------------------------------------
    # Scenario: manual inspection and device NG both enter disposition
    # ------------------------------------------------------------------
    def test_01_manual_cell_fail_creates_detected_event(self):
        order = self._order()
        insp = self._ok_round(order, 'SN-EV-001')
        serial = insp.x_fai_serial_ids[:1]
        self.assertFalse(self._events(insp),
                         'an arrived all-pass board carries no event')
        insp.cell_ids.filtered(
            lambda c: c.serial_identity_id == serial
        ).write({'manual_result': 'fail'})
        events = self._events(insp)
        self.assertEqual(len(events), 1)
        self.assertEqual(events.action, 'detected')
        self.assertEqual(events.state_after, 'pending')
        self.assertFalse(events.state_before,
                         'a first NG has no prior disposition state')
        dispositions = insp._oqc_current_dispositions(serial)
        self.assertEqual(dispositions[serial.id]['state'], 'pending')
        self.assertEqual(insp.x_oqc_pending_qty, 1)
        self.assertFalse(insp.x_oqc_release_ready)
        # completing the batch yields reject: the pending board keeps the
        # release blocked with an explicit reason
        insp.action_done()
        self.assertIn(insp.result, ('fail', 'reject'))
        self.assertFalse(insp.x_oqc_release_ready)
        self.assertIn('verdict', insp.x_oqc_release_message)

    def test_02_station_ng_creates_detected_event(self):
        order = self._order()
        insp = self._ng_round(order, 'SN-EV-002')
        serial = insp.x_fai_serial_ids[:1]
        events = self._events(insp)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.action, 'detected')
        self.assertEqual(event.state_after, 'pending')
        self.assertTrue(event.history_id,
                        'the detected event cites its station pass row')
        self.assertEqual(event.defect_code_id, self.defect)
        self.assertEqual(
            event.source_key,
            'oqc-detected-%s-%s-%s' % (order.id, serial.id, event.history_id.id))
        self.assertEqual(
            insp._oqc_current_dispositions(serial)[serial.id]['state'],
            'pending')
        # device resend of the same history identity appends nothing
        self.assertFalse(
            insp._oqc_log_detected_from_history(serial, self._oqc_row(order)))
        self.assertEqual(len(self._events(insp)), 1)

    # ------------------------------------------------------------------
    # Scenario: no result cell means the board cannot be auto-cleared
    # ------------------------------------------------------------------
    def test_03_ng_fact_without_cells_stays_pending(self):
        order = self._order()
        insp = self._ok_round(order, 'SN-EV-003')
        ghost = self._serial('SN-EV-GHOST')
        insp.x_oqc_ng_serial_ids = [(4, ghost.id)]
        dispositions = insp._oqc_current_dispositions(ghost)
        self.assertEqual(dispositions[ghost.id]['state'], 'pending',
                         'an NG fact without cells is conservatively pending')
        self.assertFalse(dispositions[ghost.id]['event_id'])
        self.assertEqual(insp.x_oqc_pending_qty, 1)
        self.assertEqual(insp.x_oqc_reworking_qty, 0)
        self.assertEqual(insp.x_oqc_reinspection_qty, 0)

    # ------------------------------------------------------------------
    # Scenario: a closed board failing again re-enters disposition
    # ------------------------------------------------------------------
    def test_04_retest_passed_board_reopens_on_new_ng(self):
        order = self._order()
        insp = self._ng_round(order, 'SN-EV-004')
        serial = insp.x_fai_serial_ids[:1]
        # close the board through the private service (the retest wizard
        # of batch 3 calls the same entry)
        insp._oqc_append_events([{
            'serial_identity_id': serial.id,
            'action': 'retest',
            'state_before': 'pending',
            'state_after': 'retest_passed',
            'reason': 'Retest confirmed.',
            'defect_code_id': self.defect.id,
            'source_key': 'test-retest-%s-%s' % (insp.id, serial.id),
        }])
        self.assertEqual(
            insp._oqc_current_dispositions(serial)[serial.id]['state'],
            'retest_passed')
        # a passing edit after closure is just an audit diff (no reopen)
        insp.cell_ids.filtered(
            lambda c: c.serial_identity_id == serial
        ).write({'manual_result': 'pass'})
        self.assertEqual(
            insp._oqc_current_dispositions(serial)[serial.id]['state'],
            'retest_passed')
        # the board fails again: a NEW detected event is appended and the
        # old history stays untouched
        insp.cell_ids.filtered(
            lambda c: c.serial_identity_id == serial
        ).write({'manual_result': 'fail'})
        events = self._events(insp)
        self.assertEqual(len(events), 4)
        self.assertEqual(events[-1].action, 'detected')
        self.assertEqual(events[-1].state_before, 'retest_passed')
        self.assertEqual(events[-1].state_after, 'pending')
        self.assertEqual(events[0].action, 'detected')
        self.assertEqual(
            insp._oqc_current_dispositions(serial)[serial.id]['state'],
            'pending')

    # ------------------------------------------------------------------
    # Scenario: unknown defect code pending completion
    # ------------------------------------------------------------------
    def test_05_raw_defect_code_registers_but_never_closes(self):
        order = self._order()
        self._feed_through_a(order, 'SN-EV-005')
        res = order.sn_station_scan(self.wc_c.id, 'SN-EV-005')
        order.with_context(
            sn_wsd_ng_defect_pending=True,
            sn_wsd_oqc_defect_raw='DEV-RAW-42',
        ).sn_station_leave(res['wip_id'], 'ng')
        insp = order.x_oqc_inspection_id
        serial = insp.x_fai_serial_ids[:1]
        event = self._events(insp)[0]
        self.assertEqual(event.defect_code_raw, 'DEV-RAW-42')
        self.assertFalse(event.defect_code_id)
        # registration is allowed, closure is not until a code is set
        with self.assertRaises(UserError) as ctx:
            insp._oqc_check_action('retest', serial)
        self.assertIn('defect code', str(ctx.exception))
        with self.assertRaises(UserError) as ctx:
            insp._oqc_check_action('scrap', serial)
        self.assertIn('defect code', str(ctx.exception))
        # backfilling the code through an event unlocks the closure
        insp._oqc_append_events([{
            'serial_identity_id': serial.id,
            'action': 'result_edit',
            'state_before': 'pending',
            'state_after': 'pending',
            'reason': 'Defect code backfilled.',
            'defect_code_id': self.defect.id,
            'source_key': 'test-backfill-%s' % serial.id,
        }])
        insp._oqc_check_action('retest', serial)

    # ------------------------------------------------------------------
    # Scenario: generic freezes keep blocking
    # ------------------------------------------------------------------
    def test_06_frozen_board_rejects_disposition_actions(self):
        order = self._order()
        insp = self._ng_round(order, 'SN-EV-006')
        serial = insp.x_fai_serial_ids[:1]
        self.env['sn.wsd.serial.freeze'].create({
            'serial_identity_id': serial.id,
            'freeze_reason': 'awaiting failure analysis',
        })
        for action in ('retest', 'rework_start', 'scrap', 'concession'):
            with self.assertRaises(UserError) as ctx:
                insp._oqc_check_action(action, serial)
            self.assertIn('frozen', str(ctx.exception))
        # releasing the freeze unblocks the disposition actions again
        serial.active_freeze_id.action_release()
        self.assertEqual(serial.x_freeze_state, 'normal')
        insp._oqc_check_action('rework_start', serial)

    # ------------------------------------------------------------------
    # Scenario: the history cannot be tampered with directly
    # ------------------------------------------------------------------
    def test_07_rpc_tampering_and_cross_company_refused(self):
        Event = self.env['sn.wsd.quality.oqc.disposition.event']
        order = self._order()
        insp = self._ng_round(order, 'SN-EV-007')
        event = self._events(insp)[0]
        tamper_vals = {
            'company_id': insp.company_id.id,
            'inspection_id': insp.id,
            'mes_order_id': order.id,
            'action': 'retest',
            'source_key': 'oqc-tamper-%s' % event.id,
        }
        # a regular internal user (non-su; the test env itself is the
        # system user) cannot forge events through the generic RPC create
        staff = self.env['res.users'].create({
            'name': 'OQC Event Staff', 'login': 'oqc_event_staff',
            'email': 'oqc_event_staff@example.com',
            'group_ids': [(6, 0, self.env.ref('base.group_user').ids)],
        })
        with self.assertRaises(AccessError):
            Event.with_user(staff).create([dict(tamper_vals)])
        # a forged context flag is not the protection: non-su is refused
        with self.assertRaises(AccessError):
            Event.with_user(staff).with_context(
                sn_wsd_oqc_event_internal=True).create([dict(tamper_vals)])
        with self.assertRaises(AccessError):
            event.write({'reason': 'tamper'})
        with self.assertRaises(AccessError):
            event.unlink()
        # cross-company read is refused by the record rule
        company2 = self.env['res.company'].create({'name': 'OQC Event Co 2'})
        user2 = self.env['res.users'].create({
            'name': 'OQC Event User 2', 'login': 'oqc_event_user_2',
            'email': 'oqc_event_user_2@example.com',
            'company_id': company2.id,
            'company_ids': [(6, 0, company2.ids)],
            'group_ids': [(6, 0, self.env.ref('base.group_user').ids)],
        })
        self.assertEqual(
            Event.with_user(user2).search_count(
                [('inspection_id', '=', insp.id)]), 0)
        with self.assertRaises(AccessError):
            Event.with_user(user2).browse(event.ids).read(['id'])

    # ------------------------------------------------------------------
    # Scenario: concurrent disposition succeeds at most once
    # ------------------------------------------------------------------
    def test_08_stale_versions_and_duplicate_source_keys(self):
        Event = self.env['sn.wsd.quality.oqc.disposition.event']
        order = self._order()
        insp = self._ng_round(order, 'SN-EV-008')
        serial = insp.x_fai_serial_ids[:1]
        first = self._events(insp)[0]
        # a concurrent edit bumps the version: the page holding the older
        # event id must be refused
        insp._oqc_append_events([{
            'serial_identity_id': serial.id,
            'action': 'result_edit',
            'state_before': 'pending', 'state_after': 'pending',
            'reason': 'Values retyped.',
            'defect_code_id': self.defect.id,
            'source_key': 'oqc-result-edit-%s-%s-%s' % (
                insp.id, serial.id, first.id),
        }])
        second = self._events(insp)[-1]
        with self.assertRaises(UserError) as ctx:
            insp._oqc_check_action(
                'rework_start', serial,
                expected_versions={serial.id: first.id})
        self.assertIn('changed since', str(ctx.exception))
        insp._oqc_check_action(
            'rework_start', serial, expected_versions={serial.id: second.id})
        # the idempotency token is enforced by a unique constraint
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                Event.sudo().with_context(
                    sn_wsd_oqc_event_internal=True).create([{
                        'company_id': insp.company_id.id,
                        'inspection_id': insp.id,
                        'mes_order_id': order.id,
                        'serial_identity_id': serial.id,
                        'action': 'result_edit',
                        'state_before': 'pending', 'state_after': 'pending',
                        'operator_id': self.env.user.id,
                        'event_time': fields.Datetime.now(),
                        'source_key': second.source_key,
                    }])

    # ------------------------------------------------------------------
    # Scenario: existing data only gets a baseline backed by evidence
    # ------------------------------------------------------------------
    def test_09_baseline_builds_from_visible_evidence(self):
        Event = self.env['sn.wsd.quality.oqc.disposition.event']
        History = self.env['sn.wsd.serial.operation.history']
        order = self._order()
        insp = self._ok_round(order, 'SN-EV-B0')  # normal sample, no event
        # pre-upgrade evidence is built directly (bypassing the hooks the
        # station flow now wires): what the migration would see
        b1 = self._serial('SN-EV-B1')  # NG fact + fail cells, no evidence
        b2 = self._serial('SN-EV-B2')  # retested: ng then ok history, arrived
        b3 = self._serial('SN-EV-B3')  # confirmed scrap
        b4 = self._serial('SN-EV-B4')  # active rework voucher
        insp.x_oqc_ng_serial_ids = [(4, b1.id), (4, b3.id), (4, b4.id)]
        insp._oqc_ensure_cells(b1)
        insp.cell_ids.with_context(sn_wsd_oqc_cell_silent=True).filtered(
            lambda c: c.serial_identity_id == b1
        ).write({'manual_result': 'fail'})
        oqc_row = self._oqc_row(order)
        now = fields.Datetime.now()
        History.create([{
            'serial_identity_id': b2.id, 'mes_order_id': order.id,
            'route_operation_id': oqc_row.id, 'result': 'ng',
            'in_date': now, 'out_date': now,
        }, {
            'serial_identity_id': b2.id, 'mes_order_id': order.id,
            'route_operation_id': oqc_row.id, 'result': 'ok',
            'in_date': now, 'out_date': now,
        }])
        insp.x_fai_arrived_serial_ids = [(4, b2.id)]
        insp._oqc_ensure_cells(b2)
        reason = self.env['sn.wsd.scrap.reason'].search([], limit=1)
        if not reason:
            self.skipTest('no scrap reason configured')
        # the scrap closure requires a defect identity on the event chain
        # (spec: unknown raw codes must be completed before closure)
        insp._oqc_append_events([{
            'serial_identity_id': b3.id,
            'action': 'result_edit',
            'state_before': 'pending', 'state_after': 'pending',
            'reason': 'Defect recorded before scrap closure.',
            'defect_code_id': self.defect.id,
            'source_key': 'test-defect-b3-%s' % insp.id,
        }])
        scrap = self.env['sn.wsd.scrap.record'].create({
            'serial_identity_id': b3.id, 'production_id': self.mo.id,
            'mes_order_id': order.id,
            'route_operation_id': insp.route_operation_id.id,
            'scrap_reason_id': reason.id, 'scrap_qty': 1.0,
        })
        scrap.action_confirm_scrap()
        b4.x_rework_inspection_id = insp.id
        # a voucher board got its NG through the station flow: it carries
        # cells (the no-cells conservative case is test_03's business)
        insp._oqc_ensure_cells(b4)
        # live scrap linkage (batch 6) writes real events for B3 during
        # the fixture: the baseline only builds boards without events
        events = insp._oqc_build_baseline()
        states = {event.serial_identity_id.name: event.state_after
                  for event in events}
        self.assertEqual(states['SN-EV-B1'], 'pending')
        self.assertEqual(states['SN-EV-B2'], 'retest_passed')
        self.assertNotIn('SN-EV-B3', states,
                         'a board with live events gets no baseline')
        self.assertEqual(states['SN-EV-B4'], 'reworking')
        self.assertEqual(
            insp._oqc_current_dispositions(b3)[b3.id]['state'], 'scrapped')
        bot = self.env.ref('base.user_root')
        for event in events:
            self.assertEqual(event.action, 'baseline')
            self.assertEqual(event.operator_id, bot,
                             'the baseline never fabricates an operator')
            self.assertEqual(event.reason,
                             'Upgrade baseline from visible evidence')
            self.assertTrue(event.source_key.startswith(
                'oqc-baseline-%s-' % insp.id))
        # the normal sample board got no baseline event
        self.assertFalse(Event.search([
            ('inspection_id', '=', insp.id),
            ('serial_identity_id', '=', insp.x_fai_serial_ids[:1].id)]))
        # the derived dispositions now follow the baseline
        dispositions = insp._oqc_current_dispositions()
        self.assertEqual(dispositions[b1.id]['state'], 'pending')
        self.assertEqual(dispositions[b2.id]['state'], 'retest_passed')
        self.assertEqual(dispositions[b3.id]['state'], 'scrapped')
        self.assertEqual(dispositions[b4.id]['state'], 'reworking')
        # re-running the baseline is a no-op (idempotent source keys)
        self.assertFalse(insp._oqc_build_baseline())

    # ------------------------------------------------------------------
    # Scenario: the parent document cannot delete its history
    # ------------------------------------------------------------------
    def test_10_inspection_unlink_blocked_by_restrict_fk(self):
        order = self._order()
        insp = self._ng_round(order, 'SN-EV-010')
        self.assertTrue(self._events(insp))
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                insp.unlink()
