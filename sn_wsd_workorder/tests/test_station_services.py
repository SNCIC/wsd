from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestStationServices(TransactionCase):
    """Terminal wrapper layer: sn_station_enter / sn_station_leave /
    sn_station_report — one round trip per action, payload shape included."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.workshop = cls.env['sn.mrp.workshop'].create(
            {'name': 'WS-T', 'code': 'WST'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'LA', 'code': 'LA', 'workshop_id': cls.workshop.id,
        })
        Operation = cls.env['sn.wsd.operation']
        cls.op_in = Operation.create(
            {'name': 'OP-IN', 'code': 'IN1', 'x_station_type': 'assembly'})
        cls.op_out = Operation.create(
            {'name': 'OP-OUT', 'code': 'OUT1', 'x_station_type': 'final_test'})
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True,
        ).create({
            'name': 'RT-STATION', 'code': 'RTST',
            'x_workshop_id': cls.workshop.id,
            'state': 'confirmed',
            'x_production_side': 'single',
            'route_operation_ids': [
                (0, 0, {'operation_id': cls.op_in.id, 'sequence': 10,
                        'x_allow_entry': True}),
                (0, 0, {'operation_id': cls.op_out.id, 'sequence': 20,
                        'x_allow_exit': True,
                        'blocked_by_route_operation_ids': [(6, 0, [])]}),
            ],
            'x_daily_input_operation_id': cls.op_in.id,
            'x_daily_output_operation_id': cls.op_out.id,
            'x_workorder_input_operation_id': cls.op_in.id,
        })
        # wire the in -> out edge on the created lines
        ops = cls.route.route_operation_ids.sorted('sequence')
        ops[1].blocked_by_route_operation_ids = [(6, 0, ops[0].ids)]
        cls.env['sn.wsd.process.route.drawing'].create({
            'route_id': cls.route.id, 'x_drawing_no': 'DWG-STATION-TEST',
        })
        product = cls.env['product.product'].create({
            'name': 'P-STATION', 'uom_id': cls.env.ref('uom.product_uom_unit').id,
            'default_code': 'DWG-STATION-TEST', 'x_board_side': 'single',
        })
        mo = cls.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': 10,
            'company_id': cls.company.id,
        })
        cls.order = cls.env['sn.wsd.mes.order'].create({
            'production_id': mo.id,
            'production_line_id': cls.line.id,
            'date_plan': fields.Date.today(),
            'planned_qty': 4,
        })
        # 上线硬闸脚手架（mes-picking-lifecycle R1）：占位领料单过闸
        from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
        give_pick(cls.env, cls.order)
        cls.order.action_online()
        cls.wc_in = cls.env['mrp.workcenter'].create({
            'name': 'WC-IN', 'x_workshop_id': cls.workshop.id,
            'x_production_line_id': cls.line.id,
            'x_operation_id': cls.op_in.id,
        })
        cls.wc_out = cls.env['mrp.workcenter'].create({
            'name': 'WC-OUT', 'x_workshop_id': cls.workshop.id,
            'x_production_line_id': cls.line.id,
            'x_operation_id': cls.op_out.id,
        })

    def test_01_enter_then_leave_round_trip(self):
        """Enter returns the payload; leave works although it unlinks the
        WIP row it was keyed on (regression: reading workcenter_id after
        the unlink raised MissingError)."""
        data = self.order.sn_station_enter('SN-T1', self.wc_in.id)
        self.assertEqual(len(data['orders']), 1)
        card = data['orders'][0]
        self.assertEqual(card['op']['wip_qty'], 1)
        self.assertTrue(card['op']['is_input_point'])
        self.assertEqual(card['input_qty'], 1.0)
        self.assertEqual([w['sn'] for w in data['wip']], ['SN-T1'])
        wip_id = data['wip'][0]['id']
        payload = self.env['sn.wsd.mes.order'].sn_station_leave(wip_id, 'ok')
        self.assertFalse(payload['finished'])  # input op is not an exit op
        self.assertEqual(payload['data']['wip'], [])
        self.assertEqual(payload['data']['orders'][0]['op']['ok_qty'], 1)

    def test_02_leave_through_exit_finishes(self):
        data = self.order.sn_station_enter('SN-T2', self.wc_in.id)
        self.env['sn.wsd.mes.order'].sn_station_leave(data['wip'][0]['id'], 'ok')
        data = self.order.sn_station_enter('SN-T2', self.wc_out.id)
        payload = self.env['sn.wsd.mes.order'].sn_station_leave(
            data['wip'][0]['id'], 'ok')
        self.assertTrue(payload['finished'])
        card = next(o for o in payload['data']['orders'] if o['id'] == self.order.id)
        self.assertEqual(card['output_qty'], 1.0)
        with self.assertRaises(ValidationError):
            self.order.sn_station_enter('SN-T2', self.wc_in.id)

    def test_03_report_mode_service(self):
        # dedicated report-mode order: the shared one is online and locked
        mo = self.order.production_id
        order = self.env['sn.wsd.mes.order'].create({
            'production_id': mo.id,
            'production_line_id': self.line.id,
            'date_plan': fields.Date.today(),
            'planned_qty': 4,
            'x_manage_mode': 'report',
        })
        # 上线硬闸脚手架（mes-picking-lifecycle R1）：占位领料单过闸
        from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
        give_pick(self.env, order)
        order.action_online()
        data = order.sn_station_report(self.wc_in.id, 3)
        card = next(o for o in data['orders'] if o['id'] == order.id)
        self.assertEqual(card['op']['reported_qty'], 3.0)
        self.assertEqual(card['input_qty'], 3.0)
        with self.assertRaises(ValidationError):
            order.sn_station_report(self.wc_out.id, 1)
        order.sn_station_report(self.wc_in.id, 1)
        data = order.sn_station_report(self.wc_out.id, 2)
        card = next(o for o in data['orders'] if o['id'] == order.id)
        self.assertEqual(card['output_qty'], 2.0)

    def test_04_two_step_ng_defect_flow(self):
        """Two-step NG: sn_resolve_ng_defect resolves scanned codes and the
        leave wrapper stamps the defect on the history row."""
        defect = self.env['sn.wsd.quality.defect.code'].search(
            [('company_id', 'in', [self.company.id, False])], limit=1)
        if not defect:
            defect = self.env['sn.wsd.quality.defect.code'].create({
                'name': 'Station Defect', 'code': 'STDF',
                'category': 'other', 'severity': 'minor',
            })
        resolved = self.env['sn.wsd.mes.order'].sn_resolve_ng_defect(defect.code)
        self.assertEqual(resolved['id'], defect.id)
        self.assertFalse(
            self.env['sn.wsd.mes.order'].sn_resolve_ng_defect('NOPE-404'))
        data = self.order.sn_station_enter('SN-T4', self.wc_in.id)
        wip_id = data['wip'][0]['id']
        MesOrder = self.env['sn.wsd.mes.order']
        with self.assertRaises(ValidationError):
            MesOrder.sn_station_leave(wip_id, 'ng')  # defect is mandatory
        payload = MesOrder.sn_station_leave(
            wip_id, 'ng', False, resolved['id'])
        self.assertFalse(payload['finished'])
        history = self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id.name', '=', 'SN-T4')])
        self.assertEqual(history.result, 'ng')
        self.assertEqual(history.defect_code_id, defect)

    def test_05_scan_leave_resolves_wip(self):
        """PDA exit-only scan: a WIP SN at this operation resolves to its
        row; the payload is all the terminal needs to leave."""
        self.order.sn_station_enter('SN-T5', self.wc_in.id)
        hit = self.env['sn.wsd.mes.order'].sn_station_scan_leave(
            self.wc_in.id, 'SN-T5')
        self.assertEqual(hit['order_id'], self.order.id)
        wip = self.env['sn.wsd.serial.wip'].browse(hit['wip_id'])
        self.assertEqual(wip.serial_identity_id.name, 'SN-T5')

    def test_06_scan_leave_rejects_elsewhere_and_unknown(self):
        """Exit-only contract: no feeding, no order switching -- a WIP SN
        parked elsewhere and an unknown SN are both hard errors."""
        self.order.sn_station_enter('SN-T6', self.wc_in.id)
        MesOrder = self.env['sn.wsd.mes.order']
        with self.assertRaises(ValidationError):
            MesOrder.sn_station_scan_leave(self.wc_out.id, 'SN-T6')
        with self.assertRaises(ValidationError):
            MesOrder.sn_station_scan_leave(self.wc_in.id, 'SN-UNKNOWN-404')
        with self.assertRaises(ValidationError):
            MesOrder.sn_station_scan_leave(self.wc_in.id, '   ')

    def test_07_scan_leave_then_ng(self):
        """Resolve by scan, leave NG with a defect: the WIP row goes away
        and the history row carries the defect code."""
        defect = self.env['sn.wsd.quality.defect.code'].search(
            [('company_id', 'in', [self.company.id, False])], limit=1)
        if not defect:
            defect = self.env['sn.wsd.quality.defect.code'].create({
                'name': 'Scan Defect', 'code': 'SCND',
                'category': 'other', 'severity': 'minor',
            })
        self.order.sn_station_enter('SN-T7', self.wc_in.id)
        hit = self.env['sn.wsd.mes.order'].sn_station_scan_leave(
            self.wc_in.id, 'SN-T7')
        payload = self.env['sn.wsd.mes.order'].sn_station_leave(
            hit['wip_id'], 'ng', False, defect.id)
        self.assertFalse(payload['finished'])
        history = self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id.name', '=', 'SN-T7')])
        self.assertEqual(history.result, 'ng')
        self.assertEqual(history.defect_code_id, defect)
        self.assertFalse(self.env['sn.wsd.serial.wip'].search([
            ('serial_identity_id.name', '=', 'SN-T7')]))

    def test_08_scan_leave_then_scrap(self):
        """Resolve by scan, leave scrap with a reason: the history row is
        terminal and the native scrap order carries the MES reason."""
        # component scrapping needs a BoM on the MO and a line-side location
        component = self.env['product.product'].create({
            'name': 'C-T8', 'uom_id': self.env.ref('uom.product_uom_unit').id,
        })
        bom = self.env['mrp.bom'].create({
            'product_tmpl_id':
                self.order.production_id.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id, 'product_qty': 2.0,
            })],
        })
        self.order.production_id.bom_id = bom.id
        line_side = self.env['stock.location'].create({
            'name': 'LINE-SIDE-T8', 'usage': 'internal',
        })
        self.workshop.component_location_id = line_side.id
        reason = self.env['sn.wsd.scrap.reason'].create({
            'name': 'Scrap T8', 'code': 'SCT8',
        })
        self.order.sn_station_enter('SN-T8', self.wc_in.id)
        hit = self.env['sn.wsd.mes.order'].sn_station_scan_leave(
            self.wc_in.id, 'SN-T8')
        MesOrder = self.env['sn.wsd.mes.order']
        with self.assertRaises(ValidationError):
            MesOrder.sn_station_leave(hit['wip_id'], 'scrap')  # reason required
        payload = MesOrder.sn_station_leave(hit['wip_id'], 'scrap', reason.id)
        self.assertFalse(payload['finished'])
        history = self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id.name', '=', 'SN-T8')])
        self.assertEqual(history.result, 'scrap')
        scraps = self.env['stock.scrap'].search([
            ('x_scrap_reason_id', '=', reason.id)])
        self.assertTrue(scraps)
        self.assertFalse(self.env['sn.wsd.serial.wip'].search([
            ('serial_identity_id.name', '=', 'SN-T8')]))
