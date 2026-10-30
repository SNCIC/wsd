from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestReportLinkDisabled(TransactionCase):
    """report-daily-workbench：报工不再触发生成 FAI/OQC 检验任务，合格
    报工不再受样本台数限流（联动以注释禁用，过站路径不受影响——其回归
    由 test_fai / test_oqc_entry 的过站用例覆盖）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create(
            {'name': 'WS-RPTDIS', 'code': 'WSRD'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'LRD', 'code': 'LRD', 'workshop_id': cls.workshop.id,
        })
        cls.workshop.component_location_id = cls.env['stock.location'].create(
            {'name': 'LINESIDE-RD', 'usage': 'internal'}).id
        Operation = cls.env['sn.wsd.operation']
        cls.op_in = Operation.create({'name': 'RD-IN', 'code': 'RDIN'})
        cls.op_out = Operation.create({'name': 'RD-OUT', 'code': 'RDOUT'})
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-RD', 'code': 'RTRD', 'x_workshop_id': cls.workshop.id,
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
            {'route_id': cls.route.id, 'x_drawing_no': 'DWG-RD-TEST'})
        cls.product = cls.env['product.product'].create({
            'name': 'P-RD', 'uom_id': cls.uom_unit.id,
            'default_code': 'DWG-RD-TEST', 'x_board_side': 'single',
        })
        cls.mo = cls.env['mrp.production'].create({
            'product_id': cls.product.id, 'product_qty': 20,
            'company_id': cls.company.id,
        })
        # effective FAI scheme (sample 2) on the first operation
        cls.fai_scheme = cls.env['sn.wsd.quality.inspection.scheme'].create({
            'name': 'RD FAI SCHEME', 'code': 'RD-FAI-01',
            'inspection_type': 'fai', 'state': 'effective',
            'operation_id': cls.op_in.id,
            'sample_size': 2,
            'product_tmpl_ids': [(6, 0, cls.product.product_tmpl_id.ids)],
            'line_ids': [
                (0, 0, {'name': 'BOM check', 'item_code': 'RD-BOM',
                        'item_type': 'text', 'expected_value': 'OK'}),
            ],
        })
        # effective fixed OQC scheme (sample 2, Ac 0 / Re 1) on the output op
        cls.oqc_scheme = cls.env['sn.wsd.quality.inspection.scheme'].create({
            'name': 'RD OQC SCHEME', 'code': 'RD-OQC-01',
            'inspection_type': 'oqc', 'state': 'effective',
            'operation_id': cls.op_out.id,
            'sampling_method': 'fixed', 'lot_qty_source': 'manual',
            'sample_size': 2, 'accept_qty': 0, 'reject_qty': 1,
            'product_tmpl_ids': [(6, 0, cls.product.product_tmpl_id.ids)],
            'line_ids': [
                (0, 0, {'name': 'Voltage check', 'item_code': 'RD-VLT',
                        'item_type': 'text', 'expected_value': 'OK'}),
            ],
        })

    def _order(self, qty=10):
        order = self.env['sn.wsd.mes.order'].create({
            'production_id': self.mo.id, 'production_line_id': self.line.id,
            'date_plan': fields.Date.today(), 'planned_qty': qty,
            'x_manage_mode': 'report',
        })
        from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
        give_pick(self.env, order)
        return order

    def _op_row(self, order, op):
        return order.x_route_operation_ids.filtered(
            lambda r: r.operation_id == op)[:1]

    def test_reporting_creates_no_fai_round(self):
        """报工单首件工序首次合格报工且命中生效 FAI 方案：不生成检验轮、
        不限流，直接落账。"""
        order = self._order()
        self.assertEqual(order.x_fai_state, 'none')
        # 5 > sample_size 2: the sample-size throttle is gone with the link
        order.report_operation_qty(self._op_row(order, self.op_in), 5)
        self.assertEqual(order.x_fai_state, 'none')
        self.assertFalse(order.x_fai_inspection_ids)
        self.assertFalse(order.x_fai_inspection_id)
        reports = self.env['sn.wsd.mes.operation.report'].search([
            ('mes_order_id', '=', order.id)])
        self.assertEqual(sum(reports.mapped('qty_ok')), 5.0)

    def test_reporting_creates_no_oqc_document(self):
        """报工单首次合格报工命中生效 OQC 方案：不建抽样单、不拦报工。"""
        order = self._order()
        order.report_operation_qty(self._op_row(order, self.op_in), 5)
        self.assertFalse(order.x_oqc_inspection_id)
        # 4 > n = 2: no interception, no document
        order.report_operation_qty(self._op_row(order, self.op_out), 4)
        self.assertFalse(order.x_oqc_inspection_id)
        self.assertEqual(order.x_oqc_state, 'none')
        oqc_docs = self.env['sn.wsd.quality.inspection'].search([
            ('mes_order_id', '=', order.id), ('inspection_type', '=', 'oqc')])
        self.assertFalse(oqc_docs)
        fai_docs = self.env['sn.wsd.quality.inspection'].search([
            ('mes_order_id', '=', order.id), ('inspection_type', '=', 'fai')])
        self.assertFalse(fai_docs)
