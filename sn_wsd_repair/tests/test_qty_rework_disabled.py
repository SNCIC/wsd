from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestQtyReworkReportDisabled(TransactionCase):
    """report-daily-workbench：数量维修单报检不再回写 qty_ng 报工行
    （调用处注释禁用，_register_qty_rework_report 方法保留）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create(
            {'name': 'WS-RQTY', 'code': 'WSRQ'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'LRQ', 'code': 'LRQ', 'workshop_id': cls.workshop.id,
        })
        cls.workshop.component_location_id = cls.env['stock.location'].create(
            {'name': 'LINESIDE-RQ', 'usage': 'internal'}).id
        Operation = cls.env['sn.wsd.operation']
        cls.op_in = Operation.create({'name': 'RQ-IN', 'code': 'RQIN'})
        cls.op_out = Operation.create({'name': 'RQ-OUT', 'code': 'RQOUT'})
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-RQ', 'code': 'RTRQ', 'x_workshop_id': cls.workshop.id,
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
            {'route_id': cls.route.id, 'x_drawing_no': 'DWG-RQ-TEST'})
        cls.product = cls.env['product.product'].create({
            'name': 'P-RQ', 'uom_id': cls.uom_unit.id,
            'default_code': 'DWG-RQ-TEST', 'x_board_side': 'single',
        })
        component = cls.env['product.product'].create({
            'name': 'COMP-RQ', 'uom_id': cls.uom_unit.id, 'is_storable': True,
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
            'product_id': cls.product.id, 'product_qty': 20,
            'company_id': cls.company.id,
        })
        defect = cls.env['sn.wsd.quality.defect.code'].search(
            [('company_id', 'in', [cls.company.id, False])], limit=1)
        if not defect:
            defect = cls.env['sn.wsd.quality.defect.code'].create({
                'name': 'RQ Defect', 'code': 'RQD',
                'category': 'other', 'severity': 'minor',
            })
        cls.defect_code = defect

    def _order_online(self, qty=10):
        order = self.env['sn.wsd.mes.order'].create({
            'production_id': self.mo.id, 'production_line_id': self.line.id,
            'date_plan': fields.Date.today(), 'planned_qty': qty,
            'x_manage_mode': 'report',
        })
        from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
        give_pick(self.env, order)
        order.action_online()
        return order

    def test_qty_repair_report_writes_no_operation_report(self):
        """已上线 report 单的数量维修单（不良 3）报检：状态流转为已报检，
        不产生 qty_ng=3 的报工行。"""
        order = self._order_online()
        op_row = order.x_route_operation_ids[:1]
        repair = self.env['sn.wsd.repair.order'].create({
            'repair_mode': 'qty',
            'mes_order_id': order.id,
            'route_operation_id': op_row.id,
            'repair_qty': 3.0,
            'defect_code_id': self.defect_code.id,
            'defect_qty': 3.0,
            'defect_line_ids': [(0, 0, {
                'defect_code_id': self.defect_code.id, 'qty': 3})],
        })
        repair.action_report_repair()
        self.assertEqual(repair.state, 'reported')
        reports = self.env['sn.wsd.mes.operation.report'].search([
            ('mes_order_id', '=', order.id)])
        self.assertFalse(
            reports,
            'reporting a qty repair must not backfill an operation report')
        self.assertEqual(op_row.x_reported_ng_qty, 0.0)
