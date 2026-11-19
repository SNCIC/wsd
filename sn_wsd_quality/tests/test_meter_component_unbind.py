from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMeterComponentUnbind(TransactionCase):
    """Component unbind kernel: flip removed + unbind event row, live-order
    gate, release semantics, batch atomicity, idempotent replay and the
    trace-only guarantee (no stock move)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.workshop = cls.env['sn.mrp.workshop'].create({'name': 'UB WS', 'code': 'UBWS'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'UBL', 'code': 'UBL', 'workshop_id': cls.workshop.id})
        Operation = cls.env['sn.wsd.operation']
        cls.op_in = Operation.create({'name': 'UB-IN', 'code': 'UBIN'})
        cls.op_out = Operation.create({'name': 'UB-OUT', 'code': 'UBOUT'})
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'UB-RT', 'code': 'UBRT', 'x_workshop_id': cls.workshop.id,
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
            'route_id': cls.route.id, 'x_drawing_no': 'DWG-UB'})
        cls.product = cls.env['product.product'].create({
            'name': 'P-UB', 'uom_id': cls.env.ref('uom.product_uom_unit').id,
            'default_code': 'DWG-UB', 'x_board_side': 'single'})
        cls.production = cls.env['mrp.production'].create({
            'product_id': cls.product.id, 'product_qty': 10, 'company_id': cls.company.id})
        cls.order = cls.env['sn.wsd.mes.order'].create({
            'production_id': cls.production.id, 'production_line_id': cls.line.id,
            'date_plan': fields.Date.today(), 'planned_qty': 10})
        cls.order._setup_route()
        cls.route_operation = cls.order.x_mes_route_id.operation_ids[:1]
        cls.workcenter = cls.env['mrp.workcenter'].create({
            'name': 'UB-WC', 'code': 'UBWC', 'x_workshop_id': cls.workshop.id,
            'x_production_line_id': cls.line.id, 'x_operation_id': cls.op_in.id})
        cls.binding_model = cls.env['sn.wsd.meter.component.binding']
        cls.identity = cls.env['sn.wsd.serial.identity'].get_or_create(
            '126110000091', cls.company, origin_type='external')

    def _bind(self, identity, component_sn, component_type='main_pcb', workorder=None):
        workorder = self.route_operation if workorder is None else workorder
        return self.binding_model.register_component_bindings(
            identity,
            [{'component_type': component_type, 'component_sn': component_sn}],
            workorder=workorder)

    def test_01_unbind_flips_removed_and_logs_event(self):
        self._bind(self.identity, 'COMP-1')
        events = self.binding_model.unbind_component_bindings(
            self.identity, ['COMP-1'],
            workcenter=self.workcenter, operator_code='UBOP')
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.event_type, 'unbind')
        self.assertEqual(event.state, 'removed')
        self.assertEqual(event.component_type, 'main_pcb')
        self.assertEqual(event.component_sn, 'COMP-1')
        self.assertEqual(event.workcenter_id, self.workcenter)
        self.assertEqual(event.operator_code, 'UBOP')
        self.assertTrue(event.event_time)
        rows = self.binding_model.search([
            ('serial_identity_id', '=', self.identity.id),
            ('component_sn', '=', 'COMP-1')])
        self.assertEqual(len(rows), 2)
        old = rows.filtered(lambda row: row.event_type == 'bind')
        self.assertEqual(old.state, 'removed')

    def test_02_unbind_releases_component_for_other_parent(self):
        self._bind(self.identity, 'COMP-2')
        self.binding_model.unbind_component_bindings(self.identity, ['COMP-2'])
        other = self.env['sn.wsd.serial.identity'].get_or_create(
            '126110000092', self.company, origin_type='external')
        rebinding = self._bind(other, 'COMP-2')
        self.assertEqual(rebinding[0].state, 'active')

    def test_03_unbind_rejects_dead_order(self):
        self._bind(self.identity, 'COMP-3')
        self.order.state = 'done'
        with self.assertRaises(ValidationError):
            self.binding_model.unbind_component_bindings(self.identity, ['COMP-3'])

    def test_04_unbind_rejects_orderless_binding(self):
        self._bind(self.identity, 'COMP-4', workorder=False)
        with self.assertRaises(ValidationError):
            self.binding_model.unbind_component_bindings(self.identity, ['COMP-4'])

    def test_05_unbind_rejects_unknown_component(self):
        self._bind(self.identity, 'COMP-5')
        with self.assertRaises(ValidationError):
            self.binding_model.unbind_component_bindings(self.identity, ['COMP-9'])

    def test_06_unbind_is_trace_only(self):
        self._bind(self.identity, 'COMP-6')
        moves_before = self.env['stock.move'].search_count([])
        self.binding_model.unbind_component_bindings(self.identity, ['COMP-6'])
        self.assertEqual(self.env['stock.move'].search_count([]), moves_before)

    def test_07_unbind_event_id_replay(self):
        self._bind(self.identity, 'COMP-7')
        first = self.binding_model.unbind_component_bindings(
            self.identity, ['COMP-7'], external_event_id='UB-EVT-1')
        replay = self.binding_model.unbind_component_bindings(
            self.identity, ['COMP-7'], external_event_id='UB-EVT-1')
        self.assertEqual(first, replay)
        self.assertEqual(self.binding_model.search_count([
            ('serial_identity_id', '=', self.identity.id),
            ('event_type', '=', 'unbind'),
        ]), 1)

    def test_08_unbind_batch_is_atomic(self):
        self._bind(self.identity, 'COMP-8')
        with self.assertRaises(ValidationError):
            self.binding_model.unbind_component_bindings(
                self.identity, ['COMP-8', 'COMP-9'])
        survivors = self.binding_model.search([
            ('serial_identity_id', '=', self.identity.id),
            ('component_sn', '=', 'COMP-8'),
            ('state', '=', 'active')])
        self.assertEqual(len(survivors), 1)

    def test_09_unbind_from_scan_pda_entry(self):
        self._bind(self.identity, 'COMP-9')
        result = self.binding_model.unbind_from_scan(
            self.workcenter.id, self.identity.name, 'COMP-9')
        self.assertEqual(result['unbound'], 1)
        self.assertEqual(result['component_type'], 'Main PCB')
        event = self.binding_model.search([
            ('serial_identity_id', '=', self.identity.id),
            ('event_type', '=', 'unbind')])
        self.assertEqual(event.operator_code, self.env.user.login)
        with self.assertRaises(ValidationError):
            self.binding_model.unbind_from_scan(
                self.workcenter.id, '126999999999', 'COMP-9')
