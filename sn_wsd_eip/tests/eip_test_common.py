"""Shared station-pass fixtures for the EIP collection tests."""

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class EipCaptureCase(TransactionCase):
    """Route A(1003 FCT) -> B(1011 aging) -> C(unmapped): one mapped
    entry op, one mapped mid op, one deliberately unmapped op."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create({
            'name': 'WS-EIP', 'code': 'WSEIP'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'EIP', 'code': 'EIP', 'workshop_id': cls.workshop.id,
        })
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-EIP', 'code': 'RTEIP',
                'x_workshop_id': cls.workshop.id,
            })
        Operation = cls.env['sn.wsd.operation']
        cls.op_a = Operation.create({
            'name': 'EIP-FCT', 'code': 'EIPFCT', 'x_max_test_count': 9})
        cls.op_b = Operation.create({
            'name': 'EIP-AGING', 'code': 'EIPAG', 'x_max_test_count': 9})
        cls.op_c = Operation.create({
            'name': 'EIP-OTHER', 'code': 'EIPO', 'x_max_test_count': 9})
        cls.route.write({
            'state': 'confirmed',
            'x_production_side': 'single',
            'route_operation_ids': [
                (0, 0, {'operation_id': cls.op_a.id, 'sequence': 10}),
                (0, 0, {'operation_id': cls.op_b.id, 'sequence': 20}),
                (0, 0, {'operation_id': cls.op_c.id, 'sequence': 30}),
            ],
            'x_daily_input_operation_id': cls.op_a.id,
            'x_daily_output_operation_id': cls.op_a.id,
            'x_workorder_input_operation_id': cls.op_a.id,
        })
        cls.env['sn.wsd.process.route.drawing'].create({
            'route_id': cls.route.id, 'x_drawing_no': 'DWG-EIP'})
        route_ops = cls.route.route_operation_ids.sorted('sequence')
        route_ops[0].x_allow_entry = True
        route_ops[2].x_allow_exit = True
        route_ops[1].blocked_by_route_operation_ids = [(6, 0, route_ops[0].ids)]
        route_ops[2].blocked_by_route_operation_ids = [(6, 0, route_ops[1].ids)]
        Mapping = cls.env['sn.wsd.eip.operation.mapping']
        Mapping.create({'operation_id': cls.op_a.id, 'info_code': '1003'})
        Mapping.create({'operation_id': cls.op_b.id, 'info_code': '1011'})
        cls.defect_code = cls.env['sn.wsd.quality.defect.code'].search(
            [('company_id', 'in', [cls.company.id, False])], limit=1)
        if not cls.defect_code:
            cls.defect_code = cls.env['sn.wsd.quality.defect.code'].create({
                'name': 'EIP Defect', 'code': 'EIPD',
                'category': 'other', 'severity': 'minor',
            })

    # ------------------------------------------------------------------
    # fixtures
    # ------------------------------------------------------------------
    def _make_order_online(self):
        product = self.env['product.product'].create({
            'name': 'P-EIP', 'uom_id': self.uom_unit.id,
            'default_code': 'DWG-EIP', 'x_board_side': 'single',
            'material_specification': 'DDS102 220V 5(60)A',
        })
        mo = self.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': 10,
            'company_id': self.company.id,
        })
        order = self.env['sn.wsd.mes.order'].create({
            'production_id': mo.id,
            'production_line_id': self.line.id,
            'date_plan': fields.Date.today(),
            'planned_qty': 4,
        })
        from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
        give_pick(self.env, order)
        order.action_online()
        return order

    def _make_workcenter(self, operation):
        return self.env['mrp.workcenter'].create({
            'name': 'WC-%s' % operation.code,
            'x_workshop_id': self.workshop.id,
            'x_operation_id': operation.id,
            'x_production_line_id': self.line.id,
        })

    def _wcs(self):
        return {'a': self._make_workcenter(self.op_a),
                'b': self._make_workcenter(self.op_b),
                'c': self._make_workcenter(self.op_c)}

    def _pass(self, order, wc, sn_name, result):
        serial = order.scan_enter(sn_name, wc)
        order.leave_station(
            serial, result,
            ng_defect=self.defect_code if result == 'ng' else False)
        return serial

    def _rows(self, sn_name):
        return self.env['sn.wsd.eip.pass.record'].sudo().search([
            ('sn_name', '=', sn_name)])
