"""OQC NG-board disposition (oqc-ng-disposition): rework voucher, pass
exemption, done guard, scrap N/A and the full-lot switch."""

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOqcDisposition(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create(
            {'name': 'WS-OQCD', 'code': 'WSOQCD'})
        cls.workshop.component_location_id = cls.env['stock.location'].create(
            {'name': 'LINESIDE-OQCD', 'usage': 'internal'}).id
        cls.line = cls.env['sn.mrp.production.line'].create(
            {'name': 'LOQCD', 'code': 'LOQCD', 'workshop_id': cls.workshop.id})
        Operation = cls.env['sn.wsd.operation']
        cls.op_a = Operation.create({'name': 'OQCD-A', 'code': 'OQCDA'})
        cls.op_c = Operation.create({'name': 'OQCD-C', 'code': 'OQCDC'})
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create(
            {'name': 'RT-OQCD', 'code': 'RTOQCD', 'x_workshop_id': cls.workshop.id})
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
            {'route_id': cls.route.id, 'x_drawing_no': 'DWG-OQCD-TEST'})
        cls.product = cls.env['product.product'].create({
            'name': 'P-OQCD', 'uom_id': cls.uom_unit.id,
            'default_code': 'DWG-OQCD-TEST', 'x_board_side': 'single',
        })
        comp = cls.env['product.product'].create(
            {'name': 'COMP-OQCD', 'uom_id': cls.uom_unit.id, 'is_storable': True})
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
            'name': 'WC-OQCD-A', 'x_workshop_id': cls.workshop.id,
            'x_production_line_id': cls.line.id, 'x_operation_id': cls.op_a.id,
        })
        cls.wc_c = cls.env['mrp.workcenter'].create({
            'name': 'WC-OQCD-C', 'x_workshop_id': cls.workshop.id,
            'x_production_line_id': cls.line.id, 'x_operation_id': cls.op_c.id,
        })
        cls.scheme = cls.env['sn.wsd.quality.inspection.scheme'].create({
            'name': 'OQC DISP SCHEME', 'code': 'OQC-DISP-01',
            'inspection_type': 'oqc', 'state': 'effective',
            'operation_id': cls.op_c.id, 'sampling_method': 'fixed',
            'sample_size': 1,
            'product_tmpl_ids': [(6, 0, cls.product.product_tmpl_id.ids)],
            'line_ids': [(0, 0, {'name': 'Visual', 'item_code': 'OQC-D-VIS',
                                 'item_type': 'pass_fail'})],
        })
        cls.defect = cls.env['sn.wsd.quality.defect.code'].create({
            'name': 'OQCD NG', 'code': 'OQCDNG',
            'category': 'other', 'severity': 'minor',
        })

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

    def _ng_round(self, order, name):
        """Feed one board, pass op A OK, then leave op C with NG: the board
        lands on the inspection's NG list (the defective sample)."""
        order.sn_station_scan(self.wc_a.id, name)
        res = order.sn_station_scan(self.wc_a.id, name)
        if isinstance(res, dict) and res.get('action') == 'leave':
            order.sn_station_leave(res['wip_id'], 'ok')
        res = order.sn_station_scan(self.wc_c.id, name)
        if isinstance(res, dict) and res.get('action') == 'leave':
            order.sn_station_leave(res['wip_id'], 'ng', ng_defect_code_id=self.defect.id)
        return order.x_oqc_inspection_id

    def test_10_rework_voucher_and_rewalk(self):
        order = self._order()
        insp = self._ng_round(order, 'SN-OQCD-001')
        self.assertEqual(insp.inspection_type, 'oqc')
        serial = insp.x_fai_serial_ids[:1]
        op_a_row = order.x_mes_route_id.operation_ids.filtered(
            lambda r: r.operation_id == self.op_a)
        insp.action_rework_sn(serial, op_a_row, 'defect at A')
        self.assertEqual(serial.x_rework_inspection_id, insp.id)
        self.assertEqual(serial.x_rework_count, 1)
        # the rework authorization lands a rework_start event: the board
        # walks its disposition states (oqc-disposition-closure task 2.2)
        event = self.env['sn.wsd.quality.oqc.disposition.event'].search([
            ('inspection_id', '=', insp.id),
            ('serial_identity_id', '=', serial.id)], order='id desc',
            limit=1)
        self.assertEqual(event.action, 'rework_start')
        self.assertEqual(event.state_after, 'reworking')
        # arming creates the voucher only: no fabricated WIP or history
        # row -- the board waits for a real scan at the target station
        # (oqc-disposition-closure task 5.2)
        wip = self.env['sn.wsd.serial.wip'].search([
            ('serial_identity_id', '=', serial.id),
            ('mes_order_id', '=', order.id)])
        self.assertFalse(wip)
        self.assertEqual(serial.x_rework_operation_id, op_a_row)
        # re-walk: the real scan at A admits via the voucher, then C again
        res = order.sn_station_scan(self.wc_a.id, 'SN-OQCD-001')
        if isinstance(res, dict) and res.get('action') == 'leave':
            order.sn_station_leave(res['wip_id'], 'ok')
        history = self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id', '=', serial.id),
            ('mes_order_id', '=', order.id), ('x_is_rework', '=', True)])
        self.assertTrue(history, 're-walked pass rows carry the rework flag')
        res = order.sn_station_scan(self.wc_c.id, 'SN-OQCD-001')
        if isinstance(res, dict) and res.get('action') == 'leave':
            order.sn_station_leave(res['wip_id'], 'ok')
        # the voucher survives the OK return: it clears only on the
        # explicit retest confirmation (oqc-disposition-closure task 5.4,
        # see TestOqcReworkRoute.test_03)
        self.assertEqual(serial.x_rework_inspection_id, insp.id)
        # back at OQC with OK = awaiting re-inspection, not closed: the
        # batch verdict may complete ("passed, disposition pending") but
        # the release stays closed until the re-judgment is confirmed
        insp.invalidate_recordset()
        self.assertEqual(
            insp._oqc_current_dispositions(serial)[serial.id]['state'],
            'awaiting_reinspection')
        insp.action_done()
        insp.invalidate_recordset()
        self.assertEqual(insp.state, 'done')
        self.assertFalse(insp.x_oqc_release_ready)
        # re-judged pass on every cell + explicit retest confirmation (the
        # batch-3 wizard calls the same private service entry)
        insp.cell_ids.filtered(
            lambda c: c.serial_identity_id == serial
        ).write({'manual_result': 'pass'})
        insp._oqc_append_events([{
            'serial_identity_id': serial.id,
            'action': 'retest',
            'state_before': 'awaiting_reinspection',
            'state_after': 'retest_passed',
            'reason': 'Retest confirmed after rework.',
            'defect_code_id': self.defect.id,
            'source_key': 'test-retest-%s-%s' % (insp.id, serial.id),
        }])
        insp.action_done()
        insp.invalidate_recordset()
        self.assertEqual(insp.result, 'pass')
        self.assertTrue(insp.x_oqc_release_ready)

    def test_20_done_guard_blocks_while_reworking(self):
        # Batch verdict vs release are separate (oqc-disposition-closure
        # task 5.5): a reworking board no longer refuses the batch verdict
        # -- the doc closes as "batch passed, disposition pending" and the
        # release gate keeps blocking until the board is re-inspected.
        order = self._order()
        insp = self._ng_round(order, 'SN-OQCD-002')
        serial = insp.x_fai_serial_ids[:1]
        op_a_row = order.x_mes_route_id.operation_ids.filtered(
            lambda r: r.operation_id == self.op_a)
        insp.action_rework_sn(serial, op_a_row, 'defect at A')
        insp.action_done()
        self.assertEqual(insp.state, 'done')
        self.assertFalse(insp.x_oqc_release_ready)
        self.assertFalse(insp._oqc_passed())

    def test_40_full_lot_switch(self):
        order = self._order()
        insp = self._ng_round(order, 'SN-OQCD-004')
        # spread the cells for the sample and judge the item failed
        insp._fai_expand_result_cells()
        insp.cell_ids.write({'manual_result': 'fail'})
        insp.action_done()
        self.assertIn(insp.result, ('fail', 'reject'))
        insp.action_start_full_inspection()
        self.assertTrue(insp.x_full_inspection)
        self.assertNotEqual(insp.state, 'done')
        # full lot: a fresh board walks from the start op to the inspection
        # op and its station entry is NOT throttled by the full sample set
        order.sn_station_scan(self.wc_a.id, 'SN-OQCD-005')
        res = order.sn_station_scan(self.wc_a.id, 'SN-OQCD-005')
        if isinstance(res, dict) and res.get('action') == 'leave':
            order.sn_station_leave(res['wip_id'], 'ok')
        order.sn_station_scan(self.wc_c.id, 'SN-OQCD-005')


    def test_60_in_place_retest_needs_explicit_confirmation(self):
        # oqc-disposition-closure task 2.2 replaces the old "no failing
        # cell left = cleared" convergence: re-judging the cells pass never
        # closes a disposition by itself. d follows the disposition states,
        # the explicit retest event (batch-3 wizard entry) closes the board.
        order = self._order()
        insp = self._ng_round(order, 'SN-OQCD-007')
        serial = insp.x_fai_serial_ids[:1]
        self.assertIn('SN-OQCD-007', insp.x_oqc_ng_serial_ids.mapped('name'))
        # the inspector re-judges the NG board's cells pass on the spot
        insp.cell_ids.filtered(
            lambda c: c.serial_identity_id.name == 'SN-OQCD-007'
        ).write({'manual_result': 'pass'})
        # the batch completes with its verdict (d = 1 >= Re = 1 -> reject)
        # and the board stays on the NG list awaiting disposition
        insp.action_done()
        insp.invalidate_recordset()
        self.assertEqual(insp.result, 'reject')
        self.assertIn('SN-OQCD-007',
                      insp.x_oqc_ng_serial_ids.mapped('name'))
        self.assertFalse(insp.x_oqc_release_ready)
        # explicit confirmation on the reopened document: d recomputes and
        # the re-completion re-judges pass on the same AQL snapshot
        insp._oqc_reopen_for_disposition()
        insp._oqc_append_events([{
            'serial_identity_id': serial.id,
            'action': 'retest',
            'state_before': 'pending',
            'state_after': 'retest_passed',
            'reason': 'Retest confirmed.',
            'defect_code_id': self.defect.id,
            'source_key': 'test-retest-%s-%s' % (insp.id, serial.id),
        }])
        insp.invalidate_recordset()
        self.assertEqual(insp.sample_defect_qty, 0)
        insp.action_done()
        insp.invalidate_recordset()
        self.assertEqual(insp.result, 'pass')
        self.assertTrue(insp.x_oqc_release_ready)

    def test_50_scrap_marks_cells_na(self):
        Scrap = self.env['sn.wsd.scrap.record']
        order = self._order()
        insp = self._ng_round(order, 'SN-OQCD-006')
        insp._fai_expand_result_cells()
        serial = insp.x_fai_serial_ids[:1]
        reason = self.env['sn.wsd.scrap.reason'].search([], limit=1)
        if not reason:
            self.skipTest('no scrap reason configured')
        scrap = Scrap.create({
            'serial_identity_id': serial.id,
            'production_id': self.mo.id,
            'mes_order_id': order.id,
            'route_operation_id': insp.route_operation_id.id,
            'scrap_reason_id': reason.id,
            'scrap_qty': 1.0,
        })
        scrap.action_confirm_scrap()
        self.assertEqual(set(insp.cell_ids.mapped('result')), {'na'})
        self.assertFalse(serial.x_rework_inspection_id)
