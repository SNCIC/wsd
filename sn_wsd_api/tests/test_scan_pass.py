from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestScanPass(TransactionCase):
    """Device-API scan-pass orchestration on the unified foundation."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.workshop = cls.env['sn.mrp.workshop'].create({'name': 'API WS', 'code': 'APIWS'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'APIL', 'code': 'APIL', 'workshop_id': cls.workshop.id})
        Operation = cls.env['sn.wsd.operation']
        cls.op_in = Operation.create({'name': 'API-IN', 'code': 'APIIN', 'x_station_type': 'assembly'})
        cls.op_out = Operation.create({'name': 'API-OUT', 'code': 'APIOUT', 'x_station_type': 'final_test'})
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'API-RT', 'code': 'APIRT', 'x_workshop_id': cls.workshop.id,
                'state': 'confirmed', 'x_production_side': 'single',
                'route_operation_ids': [
                    (0, 0, {'operation_id': cls.op_in.id, 'sequence': 10, 'x_allow_entry': True}),
                    (0, 0, {'operation_id': cls.op_out.id, 'sequence': 20, 'x_allow_exit': True}),
                ],
                'x_daily_input_operation_id': cls.op_in.id,
                'x_daily_output_operation_id': cls.op_out.id,
                'x_workorder_input_operation_id': cls.op_in.id,
            })
        ops = cls.route.route_operation_ids.sorted('sequence')
        ops[1].blocked_by_route_operation_ids = [(6, 0, ops[0].ids)]
        cls.env['sn.wsd.process.route.drawing'].create({
            'route_id': cls.route.id, 'x_drawing_no': 'DWG-API'})
        cls.product = cls.env['product.product'].create({
            'name': 'P-API', 'uom_id': cls.env.ref('uom.product_uom_unit').id,
            'default_code': 'DWG-API', 'x_board_side': 'single'})
        cls.production = cls.env['mrp.production'].create({
            'product_id': cls.product.id, 'product_qty': 100, 'company_id': cls.company.id})
        cls.order = cls.env['sn.wsd.mes.order'].create({
            'production_id': cls.production.id, 'production_line_id': cls.line.id,
            'date_plan': fields.Date.today(), 'planned_qty': 100})
        cls.order.action_online()
        cls.wc_in = cls.env['mrp.workcenter'].create({
            'name': 'API-WC-IN', 'code': 'APIWCIN', 'x_workshop_id': cls.workshop.id,
            'x_production_line_id': cls.line.id, 'x_operation_id': cls.op_in.id})
        cls.employee = cls.env['hr.employee'].search([('barcode', '=', 'APIOP')], limit=1) or cls.env['hr.employee'].create({'name': 'API Op', 'barcode': 'APIOP'})
        cls.defect = cls.env['sn.wsd.quality.defect.code'].create({
            'name': 'API Defect', 'code': 'APID',
            'category': 'other', 'severity': 'minor'})
        cls.service = cls.env['sn.wsd.api.service']

    def _payload(self, **kw):
        payload = {
            'M_DATA_AUTH': 'HQ',
            'M_SN': 'SN-API-001',
            'M_WORK_STATIONSN': 'APIWCIN',
            'M_EMP': 'APIOP',
            'M_TEST_RESULT': 'OK',
        }
        payload.update(kw)
        return payload

    def test_01_validation_gates(self):
        with self.assertRaises(ValidationError):
            self.service.scan_pass(self._payload(M_EMP='nobody'))
        with self.assertRaises(ValidationError):
            self.service.scan_pass(self._payload(M_WORK_STATIONSN='NOPE'))
        with self.assertRaises(ValidationError):
            self.service.scan_pass(self._payload(M_TEST_RESULT='MAYBE'))

    def test_02_first_pass_feeds_and_leaves(self):
        result = self.service.scan_pass(self._payload())
        self.assertTrue(result['ok'])
        history = self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id.name', '=', 'SN-API-001')])
        self.assertEqual(history.result, 'ok')
        self.assertEqual(result['panel_qty'], 1)

    def test_03_ng_only_scanned_board(self):
        result = self.service.scan_pass(self._payload(
            M_SN='SN-API-NG', M_TEST_RESULT='NG', M_STR2='APID'))
        self.assertTrue(result['ok'])
        history = self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id.name', '=', 'SN-API-NG')])
        self.assertEqual(history.result, 'ng')
        self.assertEqual(history.defect_code_id, self.defect)

    def test_04_nameplate_resolution_and_rebind(self):
        machine = self.env['sn.wsd.serial.identity'].get_or_create(
            'SN-API-M01', self.company)
        self.env['sn.wsd.serial.binding'].create({
            'serial_identity_id': self.env['sn.wsd.serial.identity'].get_or_create(
                'NP-API', self.company).id,
            'bound_serial_identity_id': machine.id,
            'binding_type': 'nameplate',
        })
        resolved = self.service._resolve_identity('NP-API')
        self.assertEqual(resolved, machine)
        # rebind to a new machine keeps the old row
        machine2 = self.env['sn.wsd.serial.identity'].get_or_create(
            'SN-API-M02', self.company)
        self.service._bind_nameplate(machine2, 'NP-API')
        bindings = self.env['sn.wsd.serial.binding'].search([
            ('serial_identity_id.name', '=', 'NP-API')])
        self.assertEqual(len(bindings), 2)
        latest = self.service._resolve_identity('NP-API')
        self.assertEqual(latest, machine2)

    def test_05_component_unique_assembly(self):
        machine = self.env['sn.wsd.serial.identity'].get_or_create(
            'SN-API-M03', self.company)
        Binding = self.env['sn.wsd.meter.component.binding']
        Binding.register_component_bindings(machine, [
            {'component_type': 'main_pcb', 'component_sn': 'PCB-API-1'}])
        other = self.env['sn.wsd.serial.identity'].get_or_create(
            'SN-API-M04', self.company)
        with self.assertRaises(ValidationError):
            Binding.register_component_bindings(other, [
                {'component_type': 'main_pcb', 'component_sn': 'PCB-API-1'}])

    def test_06_process_document_check(self):
        route_op = self.order.x_mes_route_id.operation_ids[:1]
        doc_type = self.env.ref('sn_wsd_mrp.doc_type_test_plan')
        self.env['production.process.document'].create({
            'production_id': self.production.id,
            'route_operation_code': route_op.operation_id.code,
            'type_id': doc_type.id,
            'code_ids': [(0, 0, {'code': 'TPLAN-A'})],
        })
        with self.assertRaises(ValidationError):
            self.service._check_process_documents(
                self.production, route_op, {'M_TEST_PLAN': 'TPLAN-B'})
        self.service._check_process_documents(
            self.production, route_op, {'M_TEST_PLAN': 'TPLAN-A'})
        # not uploaded -> not checked
        self.service._check_process_documents(
            self.production, route_op, {})

    def test_07_sn_generation(self):
        identity = self.order.generate_sn()
        self.assertTrue(identity.name)
        wizard = self.env['sn.wsd.generate.sn.wizard'].create({
            'mes_order_id': self.order.id, 'quantity': 3})
        action = wizard.action_generate()
        self.assertEqual(len(action['domain'][0][2]), 3)
        # next-sn service
        result = self.service.request_next_sn({'M_WORK_STATIONSN': 'APIWCIN'})
        self.assertTrue(result['ok'])

    def test_08_panel_fanout(self):
        # SMT panel inside the order: 4 boards
        self.route.x_process_type = 'smt'
        # real flow: SNs are printed first (identity exists), then panel-associated
        Identity = self.env['sn.wsd.serial.identity']
        for sn in ('SN-PANEL-1', 'SN-PANEL-2', 'SN-PANEL-3', 'SN-PANEL-4'):
            Identity.get_or_create(sn, self.company, origin_type='laser')
        panel = self.env['sn.smt.pcb.panel'].create({
            'production_id': self.production.id,
            'product_no': 'DWG-API', 'quantity': 4,
            'board_ids': [
                (0, 0, {'board_no': 1, 'pro_sn': 'SN-PANEL-1'}),
                (0, 0, {'board_no': 2, 'pro_sn': 'SN-PANEL-2'}),
                (0, 0, {'board_no': 3, 'pro_sn': 'SN-PANEL-3'}),
                (0, 0, {'board_no': 4, 'pro_sn': 'SN-PANEL-4'}),
            ],
            'state': 'confirmed',
        })
        self.assertTrue(self.order._is_smt_route_order(),
                        msg='route type=%s, private route=%s' % (
                            self.order.x_mes_route_id.route_id.x_process_type,
                            self.order.x_mes_route_id.route_id.name))
        result = self.service.scan_pass(self._payload(M_SN='SN-PANEL-2'))
        self.assertEqual(result['panel_qty'], 4)
        for sn in ['SN-PANEL-1', 'SN-PANEL-2', 'SN-PANEL-3', 'SN-PANEL-4']:
            history = self.env['sn.wsd.serial.operation.history'].search([
                ('serial_identity_id.name', '=', sn)])
            self.assertEqual(history.result, 'ok', sn)
        # NG only marks the scanned board
        for sn in ('SN-PB2-1', 'SN-PB2-2'):
            Identity.get_or_create(sn, self.company, origin_type='laser')
        panel2 = self.env['sn.smt.pcb.panel'].create({
            'production_id': self.production.id,
            'product_no': 'DWG-API', 'quantity': 2,
            'board_ids': [
                (0, 0, {'board_no': 1, 'pro_sn': 'SN-PB2-1'}),
                (0, 0, {'board_no': 2, 'pro_sn': 'SN-PB2-2'}),
            ],
            'state': 'confirmed',
        })
        result = self.service.scan_pass(self._payload(
            M_SN='SN-PB2-1', M_TEST_RESULT='NG', M_STR2='APID'))
        self.assertEqual(result['panel_qty'], 2)
        ng = self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id.name', '=', 'SN-PB2-1')])
        ok = self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id.name', '=', 'SN-PB2-2')])
        self.assertEqual(ng.result, 'ng')
        self.assertEqual(ok.result, 'ok')

    def test_09_packing_guards(self):
        self.service.scan_pass(self._payload(M_SN='SN-API-PK'))
        identity = self.env['sn.wsd.serial.identity'].search([
            ('name', '=', 'SN-API-PK')])
        route_op = self.order.x_mes_route_id.operation_ids[:1]
        with self.assertRaises(ValidationError):
            self.service._handle_packing(
                identity, self.order, route_op, self.wc_in,
                {'M_BOX_SN': 'BOX-1'}, 'ng')
        packed = self.service._handle_packing(
            identity, self.order, route_op, self.wc_in,
            {'M_BOX_SN': 'BOX-1', 'M_PACK_MAC': 'MAC-9'}, 'ok')
        self.assertTrue(packed)
        pack = self.env['sn.wsd.meter.pack.record'].search([
            ('serial_identity_id', '=', identity.id)])
        self.assertEqual(pack.carton_no, 'BOX-1')
        self.assertEqual(pack.barcode_line_ids.mapped('value'), ['MAC-9'])
        # same SN cannot be packed twice
        with self.assertRaises(ValidationError):
            self.service._handle_packing(
                identity, self.order, route_op, self.wc_in,
                {'M_BOX_SN': 'BOX-2'}, 'ok')
