from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFaiTiming(TransactionCase):
    """FAI round timing (oqc-entry-trigger): going online only arms the
    trigger; the document follows the output — the round opens when the
    first board is fed into the first-article operation (station mode) or
    on the first qualified report (report mode)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create(
            {'name': 'WS-FAIT', 'code': 'WSFTIM'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'LFAIT', 'code': 'LFAIT', 'workshop_id': cls.workshop.id,
        })
        cls.workshop.component_location_id = cls.env['stock.location'].create(
            {'name': 'LINESIDE-FAIT', 'usage': 'internal'}).id
        Operation = cls.env['sn.wsd.operation']
        cls.op_in = Operation.create({
            'name': 'FAIT-IN', 'code': 'FTIMIN', 'x_station_type': 'assembly',
            'x_max_test_count': 3,
        })
        cls.op_out = Operation.create(
            {'name': 'FAIT-OUT', 'code': 'FTIMOUT', 'x_station_type': 'final_test'})
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-FAIT', 'code': 'RTFTIM', 'x_workshop_id': cls.workshop.id,
            })
        cls.route.write({
            'state': 'confirmed', 'x_production_side': 'single',
            'route_operation_ids': [
                (0, 0, {'operation_id': cls.op_in.id, 'sequence': 10,
                        'x_allow_entry': True}),
                (0, 0, {'operation_id': cls.op_out.id, 'sequence': 20,
                        'x_allow_exit': True}),
            ],
            'x_daily_input_operation_id': cls.op_in.id,
            'x_daily_output_operation_id': cls.op_out.id,
            'x_workorder_input_operation_id': cls.op_in.id,
        })
        ops = cls.route.route_operation_ids.sorted('sequence')
        ops[1].blocked_by_route_operation_ids = [(6, 0, ops[0].ids)]
        cls.env['sn.wsd.process.route.drawing'].create(
            {'route_id': cls.route.id, 'x_drawing_no': 'DWG-FAIT-TEST'})
        cls.product = cls.env['product.product'].create({
            'name': 'P-FAIT', 'uom_id': cls.uom_unit.id,
            'default_code': 'DWG-FAIT-TEST', 'x_board_side': 'single',
        })
        component = cls.env['product.product'].create({
            'name': 'COMP-FAIT', 'uom_id': cls.uom_unit.id, 'is_storable': True,
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
            'name': 'WC-FAIT-IN', 'x_workshop_id': cls.workshop.id,
            'x_production_line_id': cls.line.id,
            'x_operation_id': cls.op_in.id,
        })
        # FAI scheme: first-article operation = op_in (the feeding station),
        # sample size 2, one text item
        cls.scheme = cls.env['sn.wsd.quality.inspection.scheme'].create({
            'name': 'FAI TIMING SCHEME', 'code': 'FAI-TIM-01',
            'inspection_type': 'fai', 'state': 'effective',
            'operation_id': cls.op_in.id,
            'sample_size': 2,
            'product_tmpl_ids': [(6, 0, cls.product.product_tmpl_id.ids)],
            'line_ids': [
                (0, 0, {'name': 'BOM check', 'item_code': 'FAI-TIM-BOM',
                        'item_type': 'text', 'expected_value': 'OK'}),
            ],
        })

    def _order(self, qty=8):
        order = self.env['sn.wsd.mes.order'].create({
            'production_id': self.mo.id, 'production_line_id': self.line.id,
            'date_plan': fields.Date.today(), 'planned_qty': qty,
        })
        # online hard gate (mes-picking-lifecycle): placeholder pick, cancel
        from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
        gate = give_pick(self.env, order)
        order.action_online()
        gate.action_cancel()
        return order

    def _feed(self, order, name):
        return order.scan_enter(name, self.wc_in)

    def _pass_round(self, order, prefix):
        # feed both samples, leave OK (full sample set) -> all pass -> done
        for n in ('001', '002'):
            serial = self._feed(order, '%s-%s' % (prefix, n))
            order.leave_station(serial, 'ok')
        inspection = order.x_fai_inspection_id
        inspection.action_set_all_pass()
        inspection.action_done()
        return inspection

    def _fail_round(self, order, prefix):
        # feed both samples, leave OK (matrix expands), then fail every cell
        # (matrix caliber: a text value off the expectation fails) -> done
        # lands on a non-pass result
        for n in ('001', '002'):
            serial = self._feed(order, '%s-%s' % (prefix, n))
            order.leave_station(serial, 'ok')
        inspection = order.x_fai_inspection_id
        inspection.cell_ids.write({'text_value': 'NG'})
        inspection.action_done()
        return inspection

    # ---------------- going online creates nothing ----------------
    def test_10_online_alone_creates_nothing(self):
        # hitting a scheme online only arms the trigger: no document, no
        # state, no round (an empty document before any output is pointless)
        order = self._order()
        self.assertEqual(order.x_fai_state, 'none')
        self.assertFalse(order.x_fai_inspection_ids)
        self.assertFalse(order.x_fai_inspection_id)
        self.assertEqual(order.x_fai_round, 0)

    # ---------------- first feed opens the round ----------------
    def test_11_first_feed_creates_round_and_registers_sample_1(self):
        order = self._order()
        s1 = self._feed(order, 'SN-FAIT-101')
        inspection = order.x_fai_inspection_id
        self.assertTrue(inspection)
        self.assertEqual(inspection.inspection_type, 'fai')
        self.assertEqual(inspection.state, 'open')
        self.assertEqual(inspection.scheme_id, self.scheme)
        self.assertEqual(inspection.sample_size, 2)
        self.assertEqual(order.x_fai_round, 1)
        self.assertEqual(inspection.x_fai_serial_ids, s1,
                         'the first fed board lands as sample 1')
        self.assertEqual(order.x_fai_sample_count, 1)
        # the 30-minute confirmation reminder is scheduled at creation time
        # (no longer at the online moment)
        self.assertIn('First article confirmation',
                      inspection.activity_ids.mapped('summary'))
        self.assertFalse(
            inspection.activity_ids.filtered(
                lambda a: a.summary == 'First article samples ready'))

    def test_12_feeds_2_to_n_register_samples_one_doc(self):
        order = self._order()
        s1 = self._feed(order, 'SN-FAIT-201')
        s2 = self._feed(order, 'SN-FAIT-202')
        inspection = order.x_fai_inspection_id
        self.assertEqual(inspection.x_fai_serial_ids, s1 | s2)
        self.assertEqual(order.x_fai_sample_count, 2)
        self.assertEqual(len(order.x_fai_inspection_ids), 1,
                         'the same round keeps collecting samples')

    # ---------------- fail branch still opens round 2 immediately ----------------
    def test_13_fail_done_opens_round_2_immediately(self):
        # the action_done fail branch keeps creating the next round right
        # away (not lazy) so every round is its own FPY data point
        order = self._order()
        inspection1 = self._fail_round(order, 'SN-FAIT-30')
        self.assertNotEqual(inspection1.result, 'pass')
        self.assertEqual(order.x_fai_state, 'in_progress')
        self.assertEqual(order.x_fai_round, 2)
        new = order.x_fai_inspection_id
        self.assertNotEqual(new, inspection1)
        self.assertEqual(new.state, 'open')
        self.assertFalse(new.x_fai_serial_ids,
                         'the new round waits for fresh samples')
        # the gate re-arms: 2 boards fit, the 3rd is blocked
        self._feed(order, 'SN-FAIT-303')
        self._feed(order, 'SN-FAIT-304')
        with self.assertRaises(ValidationError):
            self._feed(order, 'SN-FAIT-305')

    # ---------------- re-online round is lazy too ----------------
    def test_14_reonline_round_waits_for_next_feed(self):
        order = self._order()
        inspection1 = self._pass_round(order, 'SN-FAIT-40')
        self.assertEqual(order.x_fai_state, 'passed')
        order.action_offline()
        from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
        gate = give_pick(self.env, order)
        order.action_online()
        gate.action_cancel()
        # re-online alone opens nothing: the state stays on the last
        # verdict and the history does not grow
        self.assertEqual(order.x_fai_state, 'passed')
        self.assertEqual(order.x_fai_round, 1)
        self.assertEqual(len(order.x_fai_inspection_ids), 1)
        # the next feed opens the new round and lands as its sample 1
        s3 = self._feed(order, 'SN-FAIT-403')
        self.assertEqual(order.x_fai_state, 'in_progress')
        self.assertEqual(order.x_fai_round, 2)
        self.assertEqual(order.x_fai_sample_count, 1)
        new = order.x_fai_inspection_id
        self.assertNotEqual(new, inspection1)
        self.assertEqual(new.x_fai_serial_ids, s3)
        self.assertEqual(len(order.x_fai_inspection_ids), 2)
        self.assertEqual(inspection1.state, 'done')

    # ---------------- product outside any scheme never triggers ----------------
    def test_15_no_scheme_product_never_creates(self):
        self.scheme.active = False
        order = self._order()
        for n in ('A', 'B', 'C'):
            self._feed(order, 'SN-FAIT-NO-%s' % n)
        self.assertEqual(order.x_fai_state, 'none')
        self.assertFalse(order.x_fai_inspection_ids)
        self.assertEqual(order.x_fai_round, 0)
