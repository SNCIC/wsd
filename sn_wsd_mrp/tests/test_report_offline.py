from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick


@tagged('post_install', '-at_install')
class TestReportOffline(TransactionCase):
    """report-offline（报工即开工，2026-09-01 用户规则）：
    ①报工不要求在线/上线，首笔报工把单据转入生产中（领料不可跳过）
    ②顺序锁=级联制：本工序累计(OK+报废)+本批 ≤ 前置工序累计(OK+报废)，
      多前置取最大；首工序只受配额约束
    ③配额锁（本批 ≤ 计划余量）维持原样。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create({
            'name': 'WS-REPOFF', 'code': 'WSRPO'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'RPO', 'code': 'RPO', 'workshop_id': cls.workshop.id})
        cls.bom_workshop = cls.env['sn.mrp.workshop'].create({
            'name': 'WS-RPO-BOM', 'code': 'WSRPOB'})
        wh = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1)
        if wh and wh.manufacture_steps != 'mrp_one_step' and wh.pbm_loc_id:
            cls.bom_workshop.component_location_id = cls.env['stock.location'].create({
                'name': 'RPO-BOM-COMP', 'usage': 'internal',
                'location_id': wh.pbm_loc_id.id,
            }).id
        if wh and wh.manufacture_steps == 'pbm_sam' and wh.sam_loc_id:
            cls.bom_workshop.finished_product_location_id = cls.env['stock.location'].create({
                'name': 'RPO-BOM-FP', 'usage': 'internal',
                'location_id': wh.sam_loc_id.id,
            }).id
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-RPO', 'code': 'RTRPO',
                'x_workshop_id': cls.workshop.id,
            })
        # 报废报工会从线边扣组件（_mes_scrap_components）
        cls.workshop.component_location_id = cls.env['stock.location'].create({
            'name': 'RPO-LINE-SIDE', 'usage': 'internal',
        }).id
        Operation = cls.env['sn.wsd.operation']
        cls.op_a = Operation.create({'name': 'RPO-A', 'code': 'RPOA',
                                     'x_station_type': 'assembly'})
        cls.op_b = Operation.create({'name': 'RPO-B', 'code': 'RPOB',
                                     'x_station_type': 'assembly'})
        cls.op_c = Operation.create({'name': 'RPO-C', 'code': 'RPOC',
                                     'x_station_type': 'assembly'})
        cls.op_d = Operation.create({'name': 'RPO-D', 'code': 'RPOD',
                                     'x_station_type': 'final_test'})
        cls.route.write({
            'state': 'confirmed',
            'x_production_side': 'single',
            'route_operation_ids': [
                (0, 0, {'operation_id': cls.op_a.id, 'sequence': 10}),
                (0, 0, {'operation_id': cls.op_b.id, 'sequence': 20}),
                (0, 0, {'operation_id': cls.op_c.id, 'sequence': 30}),
                (0, 0, {'operation_id': cls.op_d.id, 'sequence': 40}),
            ],
            'x_daily_input_operation_id': cls.op_a.id,
            'x_daily_output_operation_id': cls.op_d.id,
            'x_workorder_input_operation_id': cls.op_a.id,
        })
        cls.env['sn.wsd.process.route.drawing'].create({
            'route_id': cls.route.id, 'x_drawing_no': 'DWG-RPO'})
        route_ops = cls.route.route_operation_ids.sorted('sequence')
        route_ops[0].x_allow_entry = True
        route_ops[3].x_allow_exit = True
        for pred, succ in zip(route_ops, route_ops[1:]):
            succ.blocked_by_route_operation_ids = [(6, 0, pred.ids)]

    def _make_order(self, qty=20):
        product = self.env['product.product'].create({
            'name': 'P-RPO', 'uom_id': self.uom_unit.id,
            'default_code': 'DWG-RPO', 'x_board_side': 'single',
        })
        component = self.env['product.product'].create({
            'name': 'COMP-RPO', 'uom_id': self.uom_unit.id, 'is_storable': True,
        })
        self.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id,
            'product_id': product.id,
            'product_uom_id': self.uom_unit.id,
            'product_qty': 1.0,
            'type': 'normal',
            'x_workshop_id': self.bom_workshop.id,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id,
                'product_qty': 2.0,
                'product_uom_id': self.uom_unit.id,
            })],
        })
        mo = self.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': qty,
            'company_id': self.company.id,
        })
        return self.env['sn.wsd.mes.order'].create({
            'production_id': mo.id,
            'production_line_id': self.line.id,
            'date_plan': fields.Date.today(),
            'planned_qty': qty,
            'x_manage_mode': 'report',
        })

    def _op(self, order, operation):
        return order.x_route_operation_ids.filtered(
            lambda r: r.operation_id == operation)[:1]

    def _reported(self, order, operation):
        op = self._op(order, operation)
        return sum(op.report_ids.mapped(lambda r: r.qty_ok + r.qty_scrap))

    def test_01_first_report_needs_picking_then_starts(self):
        """released 未领料报工被拦；领料后首笔报工把单转入生产中。"""
        order = self._make_order()
        self.assertEqual(order.state, 'released')
        with self.assertRaises(ValidationError) as ctx:
            order.report_operation_qty(self._op(order, self.op_a), 5)
        self.assertIn('no material requisition yet', str(ctx.exception))
        give_pick(self.env, order)
        order.report_operation_qty(self._op(order, self.op_a), 20)
        self.assertEqual(order.state, 'in_progress',
                         'the first report starts the order')
        self.assertEqual(self._reported(order, self.op_a), 20.0)
        with self.assertRaises(ValidationError) as ctx:
            order.report_operation_qty(self._op(order, self.op_a), 1)
        self.assertIn('plan remainder', str(ctx.exception))

    def test_02_cascade_unlock_and_boundaries(self):
        """用户场景：A20 → B15 → C10(≤15) → D5(≤10)；超上游累计拦截。"""
        order = self._make_order()
        give_pick(self.env, order)
        order.report_operation_qty(self._op(order, self.op_a), 20)
        order.report_operation_qty(self._op(order, self.op_b), 15)
        order.report_operation_qty(self._op(order, self.op_c), 10)
        order.report_operation_qty(self._op(order, self.op_d), 5)
        self.assertEqual(order.state, 'in_progress')
        self.assertEqual(self._reported(order, self.op_b), 15.0)
        self.assertEqual(self._reported(order, self.op_c), 10.0)
        self.assertEqual(self._reported(order, self.op_d), 5.0)
        self.assertEqual(order.x_output_qty, 5.0,
                         'only the output operation qty_ok feeds the target')
        with self.assertRaises(ValidationError) as ctx:
            order.report_operation_qty(self._op(order, self.op_c), 6)
        self.assertIn('predecessors', str(ctx.exception))
        with self.assertRaises(ValidationError) as ctx:
            order.report_operation_qty(self._op(order, self.op_d), 6)
        self.assertIn('predecessors', str(ctx.exception))

    def test_03_report_after_offline(self):
        """下线后（x_online_date 清空）报工照常。"""
        order = self._make_order()
        give_pick(self.env, order)
        order.action_online()
        order.report_operation_qty(self._op(order, self.op_a), 20)
        order.action_offline()
        self.assertFalse(order.x_online_date)
        order.report_operation_qty(self._op(order, self.op_b), 15)
        self.assertEqual(self._reported(order, self.op_b), 15.0)

    def test_04_cascade_counts_scrap_not_ng(self):
        """级联口径=OK+报废：上游报废占额、NG 不占。"""
        order = self._make_order()
        give_pick(self.env, order)
        reason = self.env['sn.wsd.scrap.reason'].search([], limit=1)
        self.assertTrue(reason, 'scrap reason fixture data is required')
        component = order.production_id.bom_id.bom_line_ids.product_id
        self.env['stock.quant'].create({
            'product_id': component.id,
            'location_id': self.workshop.component_location_id.id,
            'quantity': 100,
        })
        order.report_operation_qty(self._op(order, self.op_a), 20)
        # A 上游累计 20：B 报 12 OK + 2 报废 + 2 NG（NG 不计级联）→ B 有效 14
        order.report_operation_qty(
            self._op(order, self.op_b), 12, qty_ng=2, qty_scrap=2,
            scrap_reason=reason)
        self.assertEqual(self._reported(order, self.op_b), 14.0)
        # C 上限 = B 有效累计 14：报满后再报拦
        order.report_operation_qty(self._op(order, self.op_c), 14)
        with self.assertRaises(ValidationError):
            order.report_operation_qty(self._op(order, self.op_c), 1)
