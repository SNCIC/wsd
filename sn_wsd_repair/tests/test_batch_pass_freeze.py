from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBatchPassFreeze(TransactionCase):
    """维修/质量冻结的板在批量过站预检中被自动排除（执行闸仍是最终
    裁决：leave/enter 的冻结闸照常拦）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create({
            'name': 'WS-BPFZ', 'code': 'WSFZ'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'BPFZ', 'code': 'BPF', 'workshop_id': cls.workshop.id})
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-BPFZ', 'code': 'RTFZ',
                'x_workshop_id': cls.workshop.id})
        Operation = cls.env['sn.wsd.operation']
        cls.op_a = Operation.create({
            'name': 'FZ-A', 'code': 'FZA', 'x_station_type': 'assembly',
            'x_max_test_count': 9})
        cls.op_b = Operation.create({
            'name': 'FZ-B', 'code': 'FZB', 'x_station_type': 'final_test',
            'x_max_test_count': 9})
        cls.op_c = Operation.create({
            'name': 'FZ-C', 'code': 'FZC', 'x_station_type': 'final_test',
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
            'route_id': cls.route.id, 'x_drawing_no': 'DWG-BPFZ'})
        route_ops = cls.route.route_operation_ids.sorted('sequence')
        route_ops[0].x_allow_entry = True
        route_ops[2].x_allow_exit = True
        route_ops[1].blocked_by_route_operation_ids = [(6, 0, route_ops[0].ids)]
        route_ops[2].blocked_by_route_operation_ids = [(6, 0, route_ops[1].ids)]
        cls.defect_code = cls.env['sn.wsd.quality.defect.code'].search(
            [('company_id', 'in', [cls.company.id, False])], limit=1)
        if not cls.defect_code:
            cls.defect_code = cls.env['sn.wsd.quality.defect.code'].create({
                'name': 'FZ Defect', 'code': 'FZD',
                'category': 'other', 'severity': 'minor',
            })

    def _order_online(self):
        product = self.env['product.product'].create({
            'name': 'P-BPFZ', 'uom_id': self.uom_unit.id,
            'default_code': 'DWG-BPFZ', 'x_board_side': 'single'})
        mo = self.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': 10,
            'company_id': self.company.id})
        order = self.env['sn.wsd.mes.order'].create({
            'production_id': mo.id,
            'production_line_id': self.line.id,
            'date_plan': fields.Date.today(),
            'planned_qty': 10})
        from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
        give_pick(self.env, order)
        order.action_online()
        return order

    def test_frozen_sn_excluded_and_blocked(self):
        order = self._order_online()
        wc_a = self.env['mrp.workcenter'].create({
            'name': 'WC-FZA', 'x_workshop_id': self.workshop.id,
            'x_operation_id': self.op_a.id,
            'x_production_line_id': self.line.id})
        serial = order.scan_enter('FZ-SN-1', wc_a)  # parked at A
        rop_b = order.x_route_operation_ids.filtered(
            lambda r: r.operation_id == self.op_b)
        self.assertFalse(order._batch_pass_block_reason(serial, rop_b))
        repair = self.env['sn.wsd.repair.order'].create({
            'serial_identity_id': serial.id,
            'serial_no': 'FZ-SN-1',
            'mes_order_id': order.id,
            'route_operation_id': rop_b.id,
            'defect_code_id': self.defect_code.id,
            'defect_line_ids': [(0, 0, {
                'defect_code_id': self.defect_code.id, 'qty': 1})],
        })
        reason = order._batch_pass_block_reason(serial, rop_b)
        self.assertTrue(reason)
        self.assertIn('frozen', reason)
        # execution stays the final authority: the leave gate refuses too
        with self.assertRaises(ValidationError):
            order.action_batch_pass_station(
                [serial.id], rop_b, 'equipment_failure')
        self.assertFalse(repair.state == 'done')
