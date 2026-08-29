from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMesFaiReport(TransactionCase):
    """首件检验·报工模式（add-mes-fai-report）：数量收集器。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create(
            {'name': 'WS-FAIR', 'code': 'WSFR'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'LFR', 'code': 'LFR', 'workshop_id': cls.workshop.id,
        })
        cls.workshop.component_location_id = cls.env['stock.location'].create(
            {'name': 'LINESIDE-FAIR', 'usage': 'internal'}).id
        Operation = cls.env['sn.wsd.operation']
        cls.op_in = Operation.create({
            'name': 'FAIR-IN', 'code': 'FRIN', 'x_station_type': 'assembly',
            'x_max_test_count': 3,
        })
        cls.op_out = Operation.create(
            {'name': 'FAIR-OUT', 'code': 'FROUT', 'x_station_type': 'final_test'})
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-FAIR', 'code': 'RTFR', 'x_workshop_id': cls.workshop.id,
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
            {'route_id': cls.route.id, 'x_drawing_no': 'DWG-FAIR-TEST'})
        cls.product = cls.env['product.product'].create({
            'name': 'P-FAIR', 'uom_id': cls.uom_unit.id,
            'default_code': 'DWG-FAIR-TEST', 'x_board_side': 'single',
        })
        component = cls.env['product.product'].create({
            'name': 'COMP-FAIR', 'uom_id': cls.uom_unit.id, 'is_storable': True,
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
        cls.scheme = cls.env['sn.wsd.quality.inspection.scheme'].create({
            'name': 'FAIR SCHEME', 'code': 'FAIR-01',
            'inspection_type': 'fai', 'state': 'effective',
            'operation_id': cls.op_in.id,
            'sample_size': 2,
            'product_tmpl_ids': [(6, 0, cls.product.product_tmpl_id.ids)],
            'line_ids': [
                (0, 0, {'name': 'BOM check', 'item_code': 'FAIR-BOM',
                        'item_type': 'text', 'expected_value': 'OK'}),
            ],
        })
        cls.responsible = cls.env['res.users'].create({
            'name': 'FAI Responsible', 'login': 'fai.responsible',
        })

    def _order(self, qty=10):
        order = self.env['sn.wsd.mes.order'].create({
            'production_id': self.mo.id, 'production_line_id': self.line.id,
            'date_plan': fields.Date.today(), 'planned_qty': qty,
            'x_manage_mode': 'report',
        })
        from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
        gate = give_pick(self.env, order)
        order.action_online()
        gate.action_cancel()
        return order

    def _op_row(self, order, op):
        return order.x_route_operation_ids.filtered(
            lambda r: r.operation_id == op)[:1]

    # ---------------- R1 触发融合 ----------------
    def test_10_report_order_online_arms_fai(self):
        order = self._order()
        self.assertEqual(order.x_manage_mode, 'report')
        self.assertEqual(order.x_fai_state, 'in_progress')
        self.assertEqual(order.x_fai_round, 1)
        self.assertEqual(order.x_fai_inspection_id.sample_size, 2)
        self.assertEqual(order.x_fai_sample_count, 0)

    # ---------------- R2 数量收集器 ----------------
    def test_20_within_quota_reports_accumulate(self):
        order = self._order()
        op_row = self._op_row(order, self.op_in)
        order.report_operation_qty(op_row, 2)
        self.assertEqual(order.x_fai_inspection_id.x_fai_reported_qty, 2.0)
        self.assertEqual(order.x_fai_sample_count, 2)
        self.assertIn('First article samples ready',
                      order.x_fai_inspection_id.activity_ids.mapped('summary'))

    def test_21_over_quota_blocked_whole_batch(self):
        order = self._order()
        op_row = self._op_row(order, self.op_in)
        with self.assertRaises(ValidationError):
            order.report_operation_qty(op_row, 3)
        # 部分报过之后再超额也拦（剩余 1）
        order.report_operation_qty(op_row, 1)
        with self.assertRaises(ValidationError):
            order.report_operation_qty(op_row, 2)
        order.report_operation_qty(op_row, 1)  # 恰好补满

    def test_22_pure_ng_reporting_passes(self):
        order = self._order()
        op_row = self._op_row(order, self.op_in)
        order.report_operation_qty(op_row, 0, 5)  # 调机记账
        self.assertEqual(order.x_fai_inspection_id.x_fai_reported_qty, 0.0)

    def test_23_non_fai_operation_unrestricted(self):
        order = self._order(qty=2)  # planned=2：首件报满即可达产出工序
        in_row = self._op_row(order, self.op_in)
        out_row = self._op_row(order, self.op_out)
        order.report_operation_qty(in_row, 2)  # 首件样本满额
        # 首件未判定，但产出工序（非首件工序）报工不受限
        order.report_operation_qty(out_row, 2)

    # ---------------- R3 判定联动 ----------------
    def test_30_pass_unlocks_reporting(self):
        order = self._order()
        inspection = order.x_fai_inspection_id
        op_row = self._op_row(order, self.op_in)
        order.report_operation_qty(op_row, 2)
        inspection.line_ids._set_pass_values()
        inspection.action_done()
        self.assertEqual(order.x_fai_state, 'passed')
        order.report_operation_qty(op_row, 5)  # 恢复既有配额规则

    def test_31_fail_new_round_keeps_reported_ledger(self):
        order = self._order()
        inspection = order.x_fai_inspection_id
        op_row = self._op_row(order, self.op_in)
        order.report_operation_qty(op_row, 2)
        inspection.line_ids.write(
            {'is_checked': True, 'manual_result': 'fail'})
        inspection.action_done()
        self.assertEqual(inspection.result, 'fail')
        self.assertEqual(order.x_fai_round, 2)
        new = order.x_fai_inspection_id
        self.assertEqual(new.x_fai_reported_qty, 0.0)
        # Q-B：已报合格数量不被系统改动
        reports = self.env['sn.wsd.mes.operation.report'].search([
            ('mes_order_id', '=', order.id)])
        self.assertEqual(sum(reports.mapped('qty_ok')), 2.0)
        # 限流保持：新一轮超额仍拦
        with self.assertRaises(ValidationError):
            order.report_operation_qty(op_row, 3)

    def test_32_done_guard_needs_full_samples(self):
        order = self._order()
        inspection = order.x_fai_inspection_id
        op_row = self._op_row(order, self.op_in)
        order.report_operation_qty(op_row, 1)  # 只报 1/2
        inspection.line_ids._set_pass_values()
        with self.assertRaises(UserError):
            inspection.action_done()

    # ---------------- R4 提醒对象 ----------------
    def test_40_reminder_goes_to_scheme_responsible(self):
        self.scheme.responsible_user_id = self.responsible
        order = self._order()
        inspection = order.x_fai_inspection_id
        confirm = inspection.activity_ids.filtered(
            lambda a: a.summary == 'First article confirmation')
        self.assertEqual(confirm.user_id, self.responsible)

    def test_41_reminder_falls_back_to_inspector(self):
        order = self._order()
        inspection = order.x_fai_inspection_id
        confirm = inspection.activity_ids.filtered(
            lambda a: a.summary == 'First article confirmation')
        self.assertEqual(confirm.user_id, inspection.inspector_id)
