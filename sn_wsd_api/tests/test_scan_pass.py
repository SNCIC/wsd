import json

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.sn_wsd_api.models.api_scan_pass import (
    ApiBadRequest,
    ApiForbidden,
    ApiNotFound,
    ApiUnauthorized,
    ApiUnprocessable,
)


class ScanPassFixture:
    """Shared scan-pass environment (service tests + HTTP wire tests)."""

    @classmethod
    def _setup_fixture(cls):
        cls.company = cls.env.company
        # M_DATA_AUTH resolves companies through company_registry
        cls.company.company_registry = 'HQ'
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
        # 上线硬闸脚手架（mes-picking-lifecycle R1）：占位领料单过闸
        from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
        give_pick(cls.env, cls.order)
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


@tagged('post_install', '-at_install')
class TestScanPass(ScanPassFixture, TransactionCase):
    """Device-API scan-pass orchestration on the unified foundation."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_fixture()

    def test_01_validation_gates(self):
        with self.assertRaises(ValidationError):
            self.service.scan_pass(self._payload(M_DATA_AUTH=''))
        with self.assertRaises(ValidationError):
            self.service.scan_pass(self._payload(M_DATA_AUTH='GHOST-ORG'))
        with self.assertRaises(ValidationError):
            self.service.scan_pass(self._payload(M_EMP='nobody'))
        with self.assertRaises(ValidationError):
            self.service.scan_pass(self._payload(M_WORK_STATIONSN='NOPE'))
        with self.assertRaises(ValidationError):
            self.service.scan_pass(self._payload(M_TEST_RESULT='MAYBE'))

    def test_02_first_pass_feeds_and_leaves(self):
        # spec: station-pass-history/spec/过站扫码即立历史行（在制立行）/设备 API 自动停放立行
        result = self.service.scan_pass(self._payload())
        self.assertTrue(result['ok'])
        history = self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id.name', '=', 'SN-API-001'),
            ('result', '!=', 'in_progress')])
        self.assertEqual(history.result, 'ok')
        # pass-history-on-enter: an OK at a non-end operation auto-parks the
        # board at the successor -- one in-progress ledger row shows up too
        parked = self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id.name', '=', 'SN-API-001'),
            ('result', '=', 'in_progress')])
        self.assertEqual(len(parked), 1)
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
        result = self.service.request_next_sn(
            {'M_DATA_AUTH': 'HQ', 'M_WORK_STATIONSN': 'APIWCIN'})
        self.assertTrue(result['ok'])

    # 拼版扇出停用（2026-09-12，与 api_scan_pass._pass_station_with_panel
    # 同步注释）：恢复扇出时取消本用例注释。
    # def test_08_panel_fanout(self):
    #     # SMT panel inside the order: 4 boards
    #     self.route.x_process_type = 'smt'
    #     # real flow: SNs are printed first (identity exists), then panel-associated
    #     Identity = self.env['sn.wsd.serial.identity']
    #     for sn in ('SN-PANEL-1', 'SN-PANEL-2', 'SN-PANEL-3', 'SN-PANEL-4'):
    #         Identity.get_or_create(sn, self.company, origin_type='laser')
    #     panel = self.env['sn.smt.pcb.panel'].create({
    #         'production_id': self.production.id,
    #         'product_no': 'DWG-API', 'quantity': 4,
    #         'board_ids': [
    #             (0, 0, {'board_no': 1, 'pro_sn': 'SN-PANEL-1'}),
    #             (0, 0, {'board_no': 2, 'pro_sn': 'SN-PANEL-2'}),
    #             (0, 0, {'board_no': 3, 'pro_sn': 'SN-PANEL-3'}),
    #             (0, 0, {'board_no': 4, 'pro_sn': 'SN-PANEL-4'}),
    #         ],
    #         'state': 'confirmed',
    #     })
    #     self.assertTrue(self.order._is_smt_route_order(),
    #                     msg='route type=%s, private route=%s' % (
    #                         self.order.x_mes_route_id.route_id.x_process_type,
    #                         self.order.x_mes_route_id.route_id.name))
    #     result = self.service.scan_pass(self._payload(M_SN='SN-PANEL-2'))
    #     self.assertEqual(result['panel_qty'], 4)
    #     for sn in ['SN-PANEL-1', 'SN-PANEL-2', 'SN-PANEL-3', 'SN-PANEL-4']:
    #         history = self.env['sn.wsd.serial.operation.history'].search([
    #             ('serial_identity_id.name', '=', sn),
    #             ('result', '!=', 'in_progress')])
    #         self.assertEqual(history.result, 'ok', sn)
    #     # NG only marks the scanned board
    #     for sn in ('SN-PB2-1', 'SN-PB2-2'):
    #         Identity.get_or_create(sn, self.company, origin_type='laser')
    #     panel2 = self.env['sn.smt.pcb.panel'].create({
    #         'production_id': self.production.id,
    #         'product_no': 'DWG-API', 'quantity': 2,
    #         'board_ids': [
    #             (0, 0, {'board_no': 1, 'pro_sn': 'SN-PB2-1'}),
    #             (0, 0, {'board_no': 2, 'pro_sn': 'SN-PB2-2'}),
    #         ],
    #         'state': 'confirmed',
    #     })
    #     result = self.service.scan_pass(self._payload(
    #         M_SN='SN-PB2-1', M_TEST_RESULT='NG', M_STR2='APID'))
    #     self.assertEqual(result['panel_qty'], 2)
    #     ng = self.env['sn.wsd.serial.operation.history'].search([
    #         ('serial_identity_id.name', '=', 'SN-PB2-1'),
    #         ('result', '=', 'ng')])
    #     ok = self.env['sn.wsd.serial.operation.history'].search([
    #         ('serial_identity_id.name', '=', 'SN-PB2-2'),
    #         ('result', '=', 'ok')])
    #     self.assertEqual(ng.result, 'ng')
    #     self.assertEqual(ok.result, 'ok')

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

    def test_10_wide_table_capture(self):
        """One scan-pass lands every device field on the test-result wide
        table: order context, component bindings, parsed test items and the
        mirrored craft/tooling columns."""
        route_op = self.order.x_mes_route_id.operation_ids[:1]
        self.env['production.process.document'].create({
            'production_id': self.production.id,
            'route_operation_code': route_op.operation_id.code,
            'type_id': self.env.ref('sn_wsd_mrp.doc_type_parameter_plan').id,
            'code_ids': [(0, 0, {'code': 'PLAN-WIDE'})],
        })
        detail = [
            {'item_name': 'ACV', 'low_limit': '220', 'up_limit': '230',
             'item_value': '225.1', 'item_result': 'OK'},
            {'item_name': 'I_MAX', 'low_limit': '0', 'up_limit': '10',
             'item_value': '12', 'item_result': 'NG'},
        ]
        result = self.service.scan_pass(self._payload(
            M_SN='SN-API-WIDE',
            M_DEVICE_SN='DEV-01',
            M_TOOLING='T-1|T-2',
            M_MAIN_ID='PCB-WIDE-1',
            M_MODULE_ID='MOD-WIDE-1',
            M_LEADSEAL_ID='LS-WIDE-1',
            M_PARAMETER_PLAN='PLAN-WIDE',
            M_ADDRESS='TABLE-3',
            M_TEST_DETAIL=detail,
        ))
        self.assertTrue(result['ok'])
        test_result = self.env['sn.wsd.mes.test.result'].browse(
            result['test_result_id'])
        # order context survives the pass (WIP row is already cleared)
        self.assertEqual(test_result.mes_order_id, self.order)
        self.assertTrue(test_result.route_operation_id)
        self.assertEqual(test_result.workcenter_id, self.wc_in)
        # tooling trace + device SN live on the pass result (design #6);
        # other category data stays in its own small tables
        self.assertEqual(test_result.equipment_sn, 'DEV-01')
        self.assertEqual(test_result.tooling_sns, 'T-1|T-2')
        # interface mirror columns carry the verbatim upload
        self.assertEqual(test_result.parameter_plan, 'PLAN-WIDE')
        self.assertEqual(test_result.table_position, 'TABLE-3')
        self.assertEqual(test_result.pcba_codes, 'PCB-WIDE-1')
        # parsed test items
        items = test_result.detail_ids.sorted('sequence')
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].project_name, 'ACV')
        self.assertEqual(items[0].actual_value, '225.1')
        self.assertEqual(items[1].result, 'ng')
        # component bindings registered against the pass
        bindings = self.env['sn.wsd.meter.component.binding'].search([
            ('serial_identity_id.name', '=', 'SN-API-WIDE')])
        self.assertEqual(
            sorted(bindings.mapped('component_sn')),
            ['LS-WIDE-1', 'MOD-WIDE-1', 'PCB-WIDE-1'])

    def test_11_ng_links_defect_dictionary(self):
        result = self.service.scan_pass(self._payload(
            M_SN='SN-API-DFT', M_TEST_RESULT='NG', M_STR2='APID'))
        test_result = self.env['sn.wsd.mes.test.result'].browse(
            result['test_result_id'])
        self.assertEqual(test_result.defect_code_id, self.defect)
        self.assertTrue(test_result.is_ng)
        # semantic mirror columns carry the verbatim upload
        self.assertEqual(test_result.defect_code_raw, 'APID')

    def test_12_binding_is_current_lifecycle(self):
        """Rebinding demotes the old row; rebinding an earlier pair back
        promotes its historical row; current mappings resolve in one search."""
        Identity = self.env['sn.wsd.serial.identity']
        Binding = self.env['sn.wsd.serial.binding']
        m1 = Identity.get_or_create('SN-CUR-M1', self.company)
        m2 = Identity.get_or_create('SN-CUR-M2', self.company)

        def bind(machine, source='api'):
            self.service._bind_nameplate(machine, 'NP-CUR')

        bind(m1)
        row1 = Binding.search([('serial_identity_id.name', '=', 'NP-CUR'),
                               ('bound_serial_identity_id', '=', m1.id)])
        self.assertTrue(row1.is_current)

        bind(m2)
        row1.invalidate_recordset()
        row2 = Binding.search([('serial_identity_id.name', '=', 'NP-CUR'),
                               ('bound_serial_identity_id', '=', m2.id)])
        self.assertFalse(row1.is_current)
        self.assertTrue(row2.is_current)

        # one-shot current resolution
        current = Binding.search([
            ('binding_type', '=', 'nameplate'), ('is_current', '=', True),
            ('serial_identity_id.name', '=', 'NP-CUR')])
        self.assertEqual(current.bound_serial_identity_id, m2)

        # swap back to M1: historical row is promoted again, no new row
        bind(m1)
        self.assertEqual(len(Binding.search(
            [('serial_identity_id.name', '=', 'NP-CUR')])), 2)
        row1.invalidate_recordset()
        row2.invalidate_recordset()
        self.assertTrue(row1.is_current)
        self.assertFalse(row2.is_current)

    def test_13_trace_timeline(self):
        """The trace view unions every source; a station pass shows up with
        order, operation, operator and jumps back to its source document."""
        self.service.scan_pass(self._payload(M_SN='SN-TRACE-T13'))
        events = self.env['sn.wsd.trace.event'].search([
            ('sn', '=', 'SN-TRACE-T13')])
        types = events.mapped('event_type')
        self.assertIn('station', types)
        self.assertIn('test', types)
        station = events.filtered(
            lambda e: e.event_type == 'station' and e.result != 'in_progress')
        self.assertEqual(station.operator, 'APIOP')
        self.assertEqual(station.order_no, self.order.name)
        self.assertTrue(station.operation)
        self.assertEqual(station.source_model,
                         'sn.wsd.serial.operation.history')
        test_event = events.filtered(lambda e: e.event_type == 'test')
        self.assertEqual(test_event.source_model, 'sn.wsd.mes.test.result')
        # the jump action resolves to the source record
        action = station.action_open_source()
        self.assertEqual(action['res_model'], station.source_model)
        self.assertEqual(action['res_id'], station.source_id)

    def test_13b_trace_timeline_shows_wip_station(self):
        # spec: station-pass-history/spec/相邻消费方口径/追溯时间线含当前站
        """pass-history-on-enter: an in-progress (parked) pass row surfaces
        in the trace timeline as a station event dated at its entry."""
        History = self.env['sn.wsd.serial.operation.history']
        serial = self.env['sn.wsd.serial.identity'].create({
            'name': 'SN-TRACE-WIP', 'origin_type': 'manual',
            'company_id': self.order.company_id.id,
        })
        row = History.create({
            'serial_identity_id': serial.id,
            'mes_order_id': self.order.id,
            'route_operation_id': self.order.x_route_operation_ids[:1].id,
            'result': 'in_progress',
            'in_date': fields.Datetime.now(),
        })
        events = self.env['sn.wsd.trace.event'].search([
            ('sn', '=', 'SN-TRACE-WIP'), ('event_type', '=', 'station')])
        self.assertEqual(len(events), 1)
        self.assertEqual(events.result, 'in_progress')
        self.assertEqual(events.event_time, row.in_date)
        self.assertEqual(events.source_model,
                         'sn.wsd.serial.operation.history')

    def test_14_company_resolution(self):
        """M_DATA_AUTH maps to companies through company_registry; empty and
        unknown organizations are rejected before any business side effect."""
        self.assertEqual(self.service._resolve_company('HQ'), self.company)
        other = self.env['res.company'].create({
            'name': 'API Other Co', 'company_registry': 'ORG2'})
        self.assertEqual(self.service._resolve_company('ORG2'), other)
        # the resolved company scopes the whole call: identities are looked
        # up / created inside it
        result = self.service.scan_pass(self._payload(M_SN='SN-API-ORG'))
        identity = self.env['sn.wsd.serial.identity'].search([
            ('name', '=', 'SN-API-ORG')])
        self.assertTrue(result['ok'])
        self.assertEqual(identity.company_id, self.company)


@tagged('post_install', '-at_install')
class TestScanPassHttp(ScanPassFixture, HttpCase):
    """Controller wire format: plain JSON POST, no authentication, uniform
    response shell, old paths gone."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_fixture()

    def _post(self, path, body):
        return self.url_open(
            path, data=body, headers={'Content-Type': 'application/json'})

    def test_20_wire(self):
        # legacy path removed
        res = self._post('/api/v1/scan-pass', '{}')
        self.assertEqual(res.status_code, 404)
        # non-JSON body -> uniform 400 shell
        res = self._post('/api/v1/workorders/scan-pass', 'not-json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['code'], 400)
        # missing organization -> business 400, reached without credentials
        # (error messages render in Chinese over HTTP)
        res = self._post('/api/v1/workorders/scan-pass', json.dumps({}))
        body = res.json()
        self.assertEqual(body['code'], 400)
        self.assertIn('组织机构为空', body['message'])
        # happy path: no token header, plain JSON body
        res = self._post('/api/v1/workorders/scan-pass', json.dumps(
            self._payload(M_SN='SN-HTTP-01')))
        body = res.json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(body['code'], 200)
        self.assertTrue(body['data']['ok'])

    def test_21_next_sn_wire(self):
        res = self._post('/api/v1/next-sn', json.dumps(
            {'M_DATA_AUTH': 'HQ', 'M_WORK_STATIONSN': 'APIWCIN'}))
        body = res.json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(body['code'], 200)
        self.assertTrue(body['data']['ok'])
        self.assertTrue(body['data']['sn'])


def _aoi_payload(**kw):
    payload = {
        'productSn': 'SN-AOI-001',
        'machineName': 'APIWCIN',
        'type': '接口',
        'retestResult': '失数',
        'stationResult': 'OK',
        'stationInfo': 'OK:过站成功',
        'testTime': '2026-06-10T17:13:08',
        'createTime': '2026-06-10T17:13:08',
        'fileName': 'LCAO1-3',
        'operator': 'APIOP',
        'defectDetails': [],
    }
    payload.update(kw)
    return payload


def _aoi_defect(confirmed='误报', code='LCAO1-3', name='反件', part='R101'):
    return {
        'partId': part,
        'position': 'X=12.5,Y=34.2',
        'defectCode': code,
        'defectName': name,
        'confirmedResult': confirmed,
        'imagePath': '/aoi/images/x_R101.jpg',
    }


@tagged('post_install', '-at_install')
class TestAoiResults(ScanPassFixture, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_fixture()

    def test_01_ok_pass_verbatim_details(self):
        result = self.service.submit_aoi_result(_aoi_payload(
            productSn='SN-AOI-OK',
            defectDetails=[_aoi_defect(confirmed='误报')]))
        self.assertTrue(result['ok'])
        test_result = self.env['sn.wsd.mes.test.result'].browse(
            result['test_result_id'])
        self.assertEqual(test_result.test_type, 'aoi')
        self.assertEqual(test_result.result, 'ok')
        self.assertEqual(test_result.note, 'OK:过站成功')
        self.assertEqual(test_result.tester_channel, 'LCAO1-3')
        self.assertEqual(test_result.workcenter_id, self.wc_in)
        # verbatim defect line, no dictionary validation
        line = test_result.aoi_defect_detail_ids
        self.assertEqual(len(line), 1)
        self.assertEqual(line.part_id, 'R101')
        self.assertEqual(line.defect_code, 'LCAO1-3')
        self.assertEqual(line.confirmed_result, '误报')
        self.assertFalse(test_result.defect_code_id)

    def test_02_ng_primary_defect_from_confirmed(self):
        result = self.service.submit_aoi_result(_aoi_payload(
            productSn='SN-AOI-NG', stationResult='NG',
            defectDetails=[
                _aoi_defect(confirmed='误报', part='C22'),
                _aoi_defect(confirmed='确认不良', code='APID', part='R101'),
                _aoi_defect(confirmed='确认不良', code='OTHER', part='D5'),
            ]))
        self.assertTrue(result['ok'])
        test_result = self.env['sn.wsd.mes.test.result'].browse(
            result['test_result_id'])
        self.assertEqual(test_result.result, 'ng')
        self.assertEqual(test_result.defect_code_id, self.defect)
        self.assertEqual(len(test_result.aoi_defect_detail_ids), 3)
        history = self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id', '=', test_result.serial_identity_id.id)])
        self.assertEqual(history.result, 'ng')
        self.assertEqual(history.defect_code_id, self.defect)

    def test_03_ng_without_confirmed_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            self.service.submit_aoi_result(_aoi_payload(
                stationResult='NG', productSn='SN-AOI-NG2',
                defectDetails=[_aoi_defect(confirmed='误报')]))
        self.assertIn('confirmed defect', str(ctx.exception))

    def test_04_ng_unknown_defect_code_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            self.service.submit_aoi_result(_aoi_payload(
                stationResult='NG', productSn='SN-AOI-NG3',
                defectDetails=[_aoi_defect(confirmed='确认不良', code='NOPE')]))
        self.assertIn('Defect code NOPE', str(ctx.exception))

    def test_05_missing_required_fields(self):
        with self.assertRaises(ValidationError) as ctx:
            self.service.submit_aoi_result(_aoi_payload(stationInfo=''))
        self.assertEqual(str(ctx.exception),
                         'Missing required field: stationInfo')
        bad_detail = _aoi_defect(confirmed='确认不良')
        bad_detail['defectCode'] = ''
        with self.assertRaises(ValidationError) as ctx:
            self.service.submit_aoi_result(_aoi_payload(
                stationResult='NG', productSn='SN-AOI-NG4',
                defectDetails=[bad_detail]))
        self.assertEqual(
            str(ctx.exception),
            'Missing required field: defectDetails[0].defectCode')

    def test_06_result_must_be_ok_or_ng(self):
        with self.assertRaises(ValidationError):
            self.service.submit_aoi_result(_aoi_payload(
                stationResult='HOLD', productSn='SN-AOI-H'))

    def test_07_invalid_time_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            self.service.submit_aoi_result(_aoi_payload(
                testTime='2026-13-99', productSn='SN-AOI-T'))
        self.assertIn('Invalid testTime', str(ctx.exception))

    def test_08_unknown_machine_rejected(self):
        with self.assertRaises(ValidationError):
            self.service.submit_aoi_result(_aoi_payload(
                machineName='NOWC', productSn='SN-AOI-M'))

    def test_09_log_code_idempotent(self):
        payload = _aoi_payload(productSn='SN-AOI-IDEM', logCode='LOG-AOI-1',
                               defectDetails=[_aoi_defect()])
        first = self.service.submit_aoi_result(dict(payload))
        second = self.service.submit_aoi_result(dict(payload))
        self.assertEqual(first['test_result_id'], second['test_result_id'])
        results = self.env['sn.wsd.mes.test.result'].search([
            ('external_event_id', '=', 'LOG-AOI-1')])
        self.assertEqual(len(results), 1)
        self.assertEqual(len(results.aoi_defect_detail_ids), 1)
        # the resent upload must not pass the station a second time (the OK
        # row stays single; the auto-park adds exactly one in-progress row)
        history = self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id.name', '=', 'SN-AOI-IDEM')])
        self.assertEqual(
            len(history.filtered(lambda r: r.result != 'in_progress')), 1)
        self.assertEqual(len(history), 2)

    # 拼版扇出停用（2026-09-12，AOI 同口径）：恢复扇出时取消本用例注释。
    # def test_10_panel_fanout(self):
    #     self.route.x_process_type = 'smt'
    #     Identity = self.env['sn.wsd.serial.identity']
    #     for sn in ('SN-AOI-P1', 'SN-AOI-P2'):
    #         Identity.get_or_create(sn, self.company, origin_type='laser')
    #     self.env['sn.smt.pcb.panel'].create({
    #         'production_id': self.production.id,
    #         'product_no': 'DWG-API', 'quantity': 2,
    #         'board_ids': [
    #             (0, 0, {'board_no': 1, 'pro_sn': 'SN-AOI-P1'}),
    #             (0, 0, {'board_no': 2, 'pro_sn': 'SN-AOI-P2'}),
    #         ],
    #         'state': 'confirmed',
    #     })
    #     result = self.service.submit_aoi_result(_aoi_payload(
    #         productSn='SN-AOI-P1'))
    #     self.assertTrue(result['ok'])
    #     for sn in ('SN-AOI-P1', 'SN-AOI-P2'):
    #         history = self.env['sn.wsd.serial.operation.history'].search([
    #             ('serial_identity_id.name', '=', sn),
    #             ('result', '=', 'ok')])
    #         self.assertEqual(history.result, 'ok', sn)


@tagged('post_install', '-at_install')
class TestAoiResultsHttp(ScanPassFixture, HttpCase):
    """AOI controller wire format: 201 + success message, contract error
    shell."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_fixture()

    def _post(self, body):
        return self.url_open(
            '/api/v1/aoi/results', data=body,
            headers={'Content-Type': 'application/json'})

    def test_20_wire(self):
        res = self._post(json.dumps(_aoi_payload(productSn='SN-AOI-HTTP')))
        body = res.json()
        self.assertEqual(res.status_code, 201)
        self.assertEqual(body['code'], 200)
        self.assertEqual(body['message'], 'success')
        self.assertEqual(body['data'], {})
        # missing field -> contract error shell
        res = self._post(json.dumps(_aoi_payload(stationInfo='')))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['message'],
                         'Missing required field: stationInfo')
        # NG without a confirmed defect -> graded business rejection
        res = self._post(json.dumps(_aoi_payload(
            productSn='SN-AOI-HTTP-NG', stationResult='NG',
            defectDetails=[_aoi_defect(confirmed='误报')])))
        self.assertEqual(res.status_code, 422)
        self.assertEqual(res.json()['code'], 422)


@tagged('post_install', '-at_install')
class TestLaserPrint(ScanPassFixture, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_fixture()

    def _laser(self, **kw):
        payload = {
            'M_DATA_AUTH': 'HQ',
            'workOrderNo': self.production.name,
            'quantity': 3,
            'operator': 'APIOP',
        }
        payload.update(kw)
        return payload

    def test_01_batch_reservation(self):
        result = self.service.submit_laser_print_request(self._laser())
        self.assertTrue(result['ok'])
        self.assertEqual(len(result['productSnList']), 3)
        self.assertEqual(result['panelQty'], 0)
        identities = self.env['sn.wsd.serial.identity'].search([
            ('name', 'in', result['productSnList'])])
        self.assertEqual(len(identities), 3)
        self.assertEqual(
            set(identities.mapped('origin_production_id').ids),
            {self.production.id})
        self.assertEqual(set(identities.mapped('origin_type')), {'laser'})

    def test_02_auto_panel_with_short_tail(self):
        result = self.service.submit_laser_print_request(
            self._laser(quantity=10, panelQty=4))
        serials = result['productSnList']
        panels = self.env['sn.smt.pcb.panel'].search([
            ('production_id', '=', self.production.id)])
        self.assertEqual(len(panels), 3)  # 4 + 4 + short tail 2
        quantities = panels.sorted('id').mapped('quantity')
        self.assertEqual(quantities, [4, 4, 2])
        self.assertEqual(
            panels.sorted('id')[0].board_ids.sorted('board_no').mapped('pro_sn'),
            serials[0:4])
        self.assertEqual(
            panels.sorted('id')[2].board_ids.sorted('board_no').mapped('pro_sn'),
            serials[8:10])
        self.assertEqual(set(panels.mapped('state')), {'confirmed'})
        # 拼版扇出停用（2026-09-12）：自动组拼版（panelQty 组装）保留可测，
        # "自动拼版喂给过站扇出"的断言随扇出一起注释
        # self.route.x_process_type = 'smt'
        # fanout = self.service.scan_pass(self._payload(M_SN=serials[0]))
        # self.assertEqual(fanout['panel_qty'], 4)

    def test_03_unknown_work_order(self):
        with self.assertRaises(ApiNotFound) as ctx:
            self.service.submit_laser_print_request(
                self._laser(workOrderNo='NOPE-MO'))
        self.assertIn('NOPE-MO', str(ctx.exception))

    def test_04_quantity_guards(self):
        for bad in (0, -1, 'abc', 10001):
            with self.assertRaises(ApiUnprocessable):
                self.service.submit_laser_print_request(
                    self._laser(quantity=bad))
        with self.assertRaises(ApiUnprocessable):
            self.service.submit_laser_print_request(
                self._laser(panelQty=-2))
        with self.assertRaises(ApiBadRequest):
            self.service.submit_laser_print_request(
                self._laser(M_DATA_AUTH=''))
        with self.assertRaises(ApiBadRequest):
            self.service.submit_laser_print_request(
                self._laser(workOrderNo=''))
        with self.assertRaises(ApiNotFound):
            self.service.submit_laser_print_request(
                self._laser(operator='nobody'))

    def test_05_never_repeats_across_sources(self):
        first = self.order.generate_sn().name
        result = self.service.submit_laser_print_request(self._laser())
        again = self.order.generate_sn().name
        all_sns = [first] + result['productSnList'] + [again]
        self.assertEqual(len(all_sns), len(set(all_sns)))


@tagged('post_install', '-at_install')
class TestLaserPrintHttp(ScanPassFixture, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_fixture()

    def _post(self, body):
        return self.url_open(
            '/api/v1/laser/print-requests', data=body,
            headers={'Content-Type': 'application/json'})

    def test_20_wire(self):
        res = self._post(json.dumps({
            'M_DATA_AUTH': 'HQ',
            'workOrderNo': self.production.name,
            'quantity': 5,
            'panelQty': 2,
            'operator': 'APIOP',
        }))
        body = res.json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(body['code'], 200)
        self.assertEqual(body['message'], 'OK')
        self.assertEqual(len(body['data']['productSnList']), 5)
        self.assertEqual(body['data']['quantity'], 5)
        self.assertEqual(body['data']['panelQty'], 2)
        # graded errors with Chinese messages
        res = self._post(json.dumps({
            'M_DATA_AUTH': 'HQ', 'workOrderNo': 'NOPE-MO',
            'quantity': 5, 'operator': 'APIOP'}))
        self.assertEqual(res.status_code, 404)
        self.assertIn('制造订单', res.json()['message'])
        res = self._post(json.dumps({
            'M_DATA_AUTH': 'HQ', 'workOrderNo': self.production.name,
            'quantity': 0, 'operator': 'APIOP'}))
        self.assertEqual(res.status_code, 422)
        self.assertIn('数量', res.json()['message'])
        res = self._post(json.dumps({
            'workOrderNo': self.production.name,
            'quantity': 5, 'operator': 'APIOP'}))
        self.assertEqual(res.status_code, 400)
        self.assertIn('组织机构为空', res.json()['message'])


@tagged('post_install', '-at_install')
class TestAuthCheck(ScanPassFixture, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_fixture()
        cls.auth_user = cls.env['res.users'].create({
            'name': 'API Auth User',
            'login': 'apiauth',
            'password': 'auth-pw-1',
            'email': 'apiauth@example.com',
        })
        cls.auth_employee = cls.env['hr.employee'].create({
            'name': 'API Auth Op', 'user_id': cls.auth_user.id,
            'barcode': 'APIAUTH',
        })

    def _auth(self, **kw):
        payload = {'M_DATA_AUTH': 'HQ'}
        payload.update(kw)
        return payload

    def test_01_login_ok(self):
        result = self.service.auth_check(
            self._auth(userName='apiauth'), {'password': 'auth-pw-1'})
        self.assertEqual(result['userName'], 'apiauth')
        self.assertEqual(result['employeeName'], 'API Auth Op')

    def test_02_probe(self):
        self.assertEqual(self.service.auth_check(self._auth(), {}), {})

    def test_03_wrong_password(self):
        with self.assertRaises(ApiUnauthorized):
            self.service.auth_check(
                self._auth(userName='apiauth'), {'password': 'nope'})

    def test_04_missing_fields(self):
        with self.assertRaises(ApiBadRequest):
            self.service.auth_check(self._auth(), {'password': 'x'})
        with self.assertRaises(ApiBadRequest):
            self.service.auth_check(self._auth(userName='apiauth'), {})
        with self.assertRaises(ApiBadRequest):
            self.service.auth_check({'userName': 'apiauth'}, {'password': 'x'})

    def test_05_user_without_employee(self):
        self.env['res.users'].create({
            'name': 'No Emp User', 'login': 'apinoemp',
            'password': 'auth-pw-2'})
        with self.assertRaises(ApiNotFound):
            self.service.auth_check(
                self._auth(userName='apinoemp'), {'password': 'auth-pw-2'})

    def test_06_user_not_in_company(self):
        other = self.env['res.company'].create({'name': 'AUTH Other'})
        outsider = self.env['res.users'].create({
            'name': 'Outsider', 'login': 'apiout', 'password': 'auth-pw-3'})
        outsider.write({
            'company_ids': [(6, 0, [other.id])], 'company_id': other.id})
        self.env['hr.employee'].create({
            'name': 'Outsider Emp', 'user_id': outsider.id})
        with self.assertRaises(ApiForbidden):
            self.service.auth_check(
                self._auth(userName='apiout'), {'password': 'auth-pw-3'})


@tagged('post_install', '-at_install')
class TestAuthCheckHttp(ScanPassFixture, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_fixture()
        cls.auth_user = cls.env['res.users'].create({
            'name': 'API Auth User',
            'login': 'apiauth',
            'password': 'auth-pw-1',
            'email': 'apiauth@example.com',
        })
        cls.env['hr.employee'].create({
            'name': 'API Auth Op', 'user_id': cls.auth_user.id})

    def _post(self, body):
        return self.url_open(
            '/api/v1/auth/check', data=body,
            headers={'Content-Type': 'application/json'})

    def test_20_wire_and_redaction(self):
        # probe
        res = self._post(json.dumps({'M_DATA_AUTH': 'HQ'}))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['data'], {})
        # successful login
        res = self._post(json.dumps(
            {'M_DATA_AUTH': 'HQ', 'userName': 'apiauth',
             'password': 'auth-pw-1'}))
        body = res.json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(body['data']['employeeName'], 'API Auth Op')
        # graded 401 with Chinese message
        res = self._post(json.dumps(
            {'M_DATA_AUTH': 'HQ', 'userName': 'apiauth',
             'password': 'wrong'}))
        self.assertEqual(res.status_code, 401)
        self.assertIn('账号或密码', res.json()['message'])
        # failure records persist despite the business rollback, and the
        # stored password is the redacted copy
        log = self.env['sn.wsd.api.request.log'].search(
            [('endpoint', '=', '/api/v1/auth/check')], limit=1)
        self.assertEqual(log.result_code, '401')
        self.assertEqual(log.payload.get('password'), '***')


@tagged('post_install', '-at_install')
class TestDictSearch(ScanPassFixture, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_fixture()

    def test_01_mes_orders_by_work_order(self):
        result = self.service.search_mes_orders(
            {'M_DATA_AUTH': 'HQ', 'work_order': self.production.name})
        self.assertIn(self.order.name, result)
        result = self.service.search_mes_orders(
            {'M_DATA_AUTH': 'HQ', 'work_order': 'NO-SUCH-MO'})
        self.assertEqual(result, [])
        with self.assertRaises(ApiBadRequest):
            self.service.search_mes_orders({'M_DATA_AUTH': 'HQ'})
        with self.assertRaises(ApiBadRequest):
            self.service.search_mes_orders({'work_order': self.production.name})
        with self.assertRaises(ApiNotFound):
            self.service.search_mes_orders(
                {'M_DATA_AUTH': 'GHOST', 'work_order': self.production.name})

    def test_02_work_centers(self):
        result = self.service.search_work_centers(
            {'M_DATA_AUTH': 'HQ', 'work_station': 'APIWC'})
        self.assertIn(['APIWCIN', 'API-WC-IN'], result)
        result = self.service.search_work_centers({'M_DATA_AUTH': 'HQ'})
        self.assertTrue(
            any(pair[0] == 'APIWCIN' for pair in result))

    def test_03_defect_codes(self):
        result = self.service.search_defect_codes(
            {'M_DATA_AUTH': 'HQ', 'err_name': 'APID'})
        self.assertIn(['APID', 'API Defect'], result)
        result = self.service.search_defect_codes({'M_DATA_AUTH': 'HQ'})
        self.assertTrue(
            any(pair[0] == 'APID' for pair in result))


@tagged('post_install', '-at_install')
class TestDictSearchHttp(ScanPassFixture, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_fixture()

    def _post(self, path, body):
        return self.url_open(
            path, data=body, headers={'Content-Type': 'application/json'})

    def test_20_wire(self):
        # MES orders: flat string array with device-contract message
        res = self._post('/api/v1/manufacturing-orders/by-work-order',
                         json.dumps({'M_DATA_AUTH': 'HQ',
                                     'work_order': self.production.name}))
        body = res.json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(body['message'], 'success')
        self.assertIn(self.order.name, body['data'])
        self.assertTrue(all(isinstance(item, str) for item in body['data']))
        # work centers: 2D array, empty keyword = full list
        res = self._post('/api/v1/work-centers/search',
                         json.dumps({'M_DATA_AUTH': 'HQ'}))
        body = res.json()
        self.assertEqual(body['message'], 'success')
        self.assertTrue(all(len(pair) == 2 for pair in body['data']))
        # defect codes: 2D array
        res = self._post('/api/v1/defect-codes/search',
                         json.dumps({'M_DATA_AUTH': 'HQ', 'err_name': 'APID'}))
        body = res.json()
        self.assertIn(['APID', 'API Defect'], body['data'])
        # missing work_order -> graded Chinese 400
        res = self._post('/api/v1/manufacturing-orders/by-work-order',
                         json.dumps({'M_DATA_AUTH': 'HQ'}))
        self.assertEqual(res.status_code, 400)
        self.assertIn('work_order', res.json()['message'])


@tagged('post_install', '-at_install')
class TestSnCoding(ScanPassFixture, TransactionCase):
    """SN reservation through the coding-rule engine, with legacy
    per-product sequence as the no-rule fallback."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_fixture()

    def _disable_identity_rules(self):
        self.env['sn.code.rule'].search([
            ('model_name', '=', 'sn.wsd.serial.identity')]).write(
            {'active': False})

    def _sn_rule(self):
        return self.env['sn.code.rule'].create({
            'name': 'TEST SN rule',
            'model_id': self.env['ir.model']._get_id('sn.wsd.serial.identity'),
            'target_field': 'name',
            'separator': '',
            'segment_ids': [
                (0, 0, {
                    'segment_type': 'field',
                    'field_path':
                        'origin_production_id.product_id.default_code',
                    'empty_policy': 'blank',
                }),
                (0, 0, {
                    'segment_type': 'seq',
                    'padding': 5,
                    'period': 'none',
                    'seq_impl': 'engine',
                    'group_field_paths':
                        'origin_production_id.product_id.default_code',
                }),
            ],
        })

    def test_01_rule_rendering_three_entries(self):
        self._disable_identity_rules()
        self._sn_rule()
        first = self.order.generate_sn()
        second = self.env['sn.wsd.serial.identity'].generate_for_production(
            self.production, origin_type='laser')
        third = self.service.submit_laser_print_request({
            'M_DATA_AUTH': 'HQ', 'workOrderNo': self.production.name,
            'quantity': 1, 'operator': 'APIOP'})['productSnList'][0]
        names = [first.name, second.name, third]
        self.assertTrue(all(name.startswith('DWG-API') for name in names))
        self.assertEqual(len(set(names)), 3)
        tails = sorted(int(name[len('DWG-API'):]) for name in names)
        self.assertEqual(tails, list(range(tails[0], tails[0] + 3)))

    def test_02_fallback_legacy_sequence(self):
        self._disable_identity_rules()
        Identity = self.env['sn.wsd.serial.identity']
        first = Identity.generate_for_production(
            self.production, origin_type='manual')
        second = Identity.generate_for_production(
            self.production, origin_type='manual')
        self.assertTrue(first.name.startswith('DWG-API'))
        self.assertEqual(int(second.name[len('DWG-API'):]),
                         int(first.name[len('DWG-API'):]) + 1)

    def test_03_backfill_continuity(self):
        self._disable_identity_rules()
        Identity = self.env['sn.wsd.serial.identity']
        Identity.create({
            'name': 'DWG-API00123', 'company_id': self.company.id,
            'origin_type': 'laser', 'origin_production_id': self.production.id})
        rule = self._sn_rule()
        self.env['sn.serial.identity.code.seed']._backfill_identity_counters(rule)
        nxt = Identity.generate_for_production(
            self.production, origin_type='laser')
        self.assertEqual(nxt.name, 'DWG-API00124')
