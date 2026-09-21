from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBatchPassFaiGate(TransactionCase):
    """FAI 命中禁位：首件闸只守投入口，命中 FAI 方案的中间工序批量过站
    必须在入口被拒（否则首件被静默跳过）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create({
            'name': 'WS-BPFAI', 'code': 'WSBF'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'BPFAI', 'code': 'BPF', 'workshop_id': cls.workshop.id})
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-BPFAI', 'code': 'RTBF',
                'x_workshop_id': cls.workshop.id})
        Operation = cls.env['sn.wsd.operation']
        cls.op_a = Operation.create({
            'name': 'BF-A', 'code': 'BFA', 'x_station_type': 'assembly',
            'x_max_test_count': 9})
        cls.op_b = Operation.create({
            'name': 'BF-B', 'code': 'BFB', 'x_station_type': 'final_test',
            'x_max_test_count': 9})
        cls.op_c = Operation.create({
            'name': 'BF-C', 'code': 'BFC', 'x_station_type': 'final_test',
            'x_max_test_count': 9})
        cls.route.write({
            'state': 'confirmed',
            'x_production_side': 'single',
            'route_operation_ids': [
                (0, 0, {'operation_id': cls.op_a.id, 'sequence': 10}),
                (0, 0, {'operation_id': cls.op_b.id, 'sequence': 20}),
                (0, 0, {'operation_id': cls.op_c.id, 'sequence': 30}),
            ],
            'x_daily_input_operation_id': cls.op_a.id,
            'x_daily_output_operation_id': cls.op_c.id,
            'x_workorder_input_operation_id': cls.op_a.id,
        })
        cls.env['sn.wsd.process.route.drawing'].create({
            'route_id': cls.route.id, 'x_drawing_no': 'DWG-BPFAI'})
        route_ops = cls.route.route_operation_ids.sorted('sequence')
        route_ops[0].x_allow_entry = True
        route_ops[2].x_allow_exit = True
        route_ops[1].blocked_by_route_operation_ids = [(6, 0, route_ops[0].ids)]
        route_ops[2].blocked_by_route_operation_ids = [(6, 0, route_ops[1].ids)]

    def _order(self):
        product = self.env['product.product'].create({
            'name': 'P-BPFAI', 'uom_id': self.uom_unit.id,
            'default_code': 'DWG-BPFAI', 'x_board_side': 'single',
        })
        mo = self.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': 10,
            'company_id': self.company.id})
        return self.env['sn.wsd.mes.order'].create({
            'production_id': mo.id,
            'production_line_id': self.line.id,
            'date_plan': fields.Date.today(),
            'planned_qty': 10})

    def test_fai_scheme_blocks_batch_pass(self):
        order = self._order()
        rop_b = order.x_route_operation_ids.filtered(
            lambda r: r.operation_id == self.op_b)
        order._batch_pass_gate_checks(rop_b)  # no scheme: plain op passes
        scheme = self.env['sn.wsd.quality.inspection.scheme'].create({
            'code': 'FAI-BFB', 'name': 'FAI at BF-B',
            'inspection_type': 'fai',
            'operation_id': self.op_b.id,
        })
        with self.assertRaises(ValidationError) as err:
            order._batch_pass_gate_checks(rop_b)
        self.assertIn('first-article', str(err.exception))
        scheme.active = False
        order._batch_pass_gate_checks(rop_b)  # archived: open again
