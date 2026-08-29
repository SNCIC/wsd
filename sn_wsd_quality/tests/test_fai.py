from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMesFai(TransactionCase):
    """首件检验 FAI（add-mes-fai）：上线触发/样本限流/出站登记/判定联动。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create(
            {'name': 'WS-FAI', 'code': 'WSFAI'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'LFAI', 'code': 'LFAI', 'workshop_id': cls.workshop.id,
        })
        cls.workshop.component_location_id = cls.env['stock.location'].create(
            {'name': 'LINESIDE-FAI', 'usage': 'internal'}).id
        Operation = cls.env['sn.wsd.operation']
        cls.op_in = Operation.create({
            'name': 'FAI-IN', 'code': 'FAIIN', 'x_station_type': 'assembly',
            'x_max_test_count': 3,
        })
        cls.op_out = Operation.create(
            {'name': 'FAI-OUT', 'code': 'FAIOUT', 'x_station_type': 'final_test'})
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-FAI', 'code': 'RTFAI', 'x_workshop_id': cls.workshop.id,
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
            {'route_id': cls.route.id, 'x_drawing_no': 'DWG-FAI-TEST'})
        cls.product = cls.env['product.product'].create({
            'name': 'P-FAI', 'uom_id': cls.uom_unit.id,
            'default_code': 'DWG-FAI-TEST', 'x_board_side': 'single',
        })
        component = cls.env['product.product'].create({
            'name': 'COMP-FAI', 'uom_id': cls.uom_unit.id, 'is_storable': True,
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
            'product_id': cls.product.id, 'product_qty': 10,
            'company_id': cls.company.id,
        })
        cls.wc_in = cls.env['mrp.workcenter'].create({
            'name': 'WC-FAI-IN', 'x_workshop_id': cls.workshop.id,
            'x_production_line_id': cls.line.id,
            'x_operation_id': cls.op_in.id,
        })
        cls.defect = cls.env['sn.wsd.quality.defect.code'].create({
            'name': 'FAI NG', 'code': 'FAING',
            'category': 'other', 'severity': 'minor',
        })
        # FAI 方案：首件工序=op_in，样本台数 2，两条检验行
        cls.scheme = cls.env['sn.wsd.quality.inspection.scheme'].create({
            'name': 'FAI SCHEME', 'code': 'FAI-01',
            'inspection_type': 'fai', 'state': 'effective',
            'operation_id': cls.op_in.id,
            'sample_size': 2,
            'product_tmpl_ids': [(6, 0, cls.product.product_tmpl_id.ids)],
            'line_ids': [
                (0, 0, {'name': 'BOM check', 'item_code': 'FAI-BOM',
                        'item_type': 'text', 'expected_value': 'OK'}),
                (0, 0, {'name': 'Polarity check', 'item_code': 'FAI-POL',
                        'item_type': 'text', 'expected_value': 'OK'}),
            ],
        })

    def _order(self, qty=8, mode='station'):
        order = self.env['sn.wsd.mes.order'].create({
            'production_id': self.mo.id, 'production_line_id': self.line.id,
            'date_plan': fields.Date.today(), 'planned_qty': qty,
        })
        if mode != 'station':
            order.x_manage_mode = mode
        # 上线硬闸（mes-picking-lifecycle）：占位领料单过闸后取消
        from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
        gate = give_pick(self.env, order)
        order.action_online()
        gate.action_cancel()
        return order

    def _feed(self, order, name):
        return order.scan_enter(name, self.wc_in)

    def _ng(self, order, serial):
        order.leave_station(serial, 'ng', ng_defect=self.defect)

    # ---------------- R1 触发与轮次 ----------------
    def test_10_online_hit_creates_round_1(self):
        order = self._order()
        self.assertEqual(order.x_fai_state, 'in_progress')
        self.assertEqual(order.x_fai_round, 1)
        inspection = order.x_fai_inspection_id
        self.assertEqual(inspection.inspection_type, 'fai')
        self.assertEqual(inspection.state, 'open')
        self.assertEqual(inspection.sample_size, 2)
        self.assertEqual(len(inspection.line_ids), 2,
                         'scheme lines snapshot')
        self.assertEqual(inspection.scheme_id, self.scheme)
        # 30 分钟确认提醒
        self.assertIn('First article confirmation',
                      inspection.activity_ids.mapped('summary'))

    def test_11_no_scheme_no_fai(self):
        self.scheme.active = False
        order = self._order()
        self.assertEqual(order.x_fai_state, 'none')
        self.assertFalse(order.x_fai_inspection_ids)

    def test_11b_non_iqc_scheme_requires_operation(self):
        from odoo.exceptions import ValidationError as VE
        with self.assertRaises(VE):
            self.env['sn.wsd.quality.inspection.scheme'].create({
                'name': 'FAI NO OP', 'code': 'FAI-NOOP',
                'inspection_type': 'fai', 'state': 'effective',
                'operation_id': False,
                'sample_size': 2,
                'product_tmpl_ids': [(6, 0, self.product.product_tmpl_id.ids)],
            })

    def test_12_reonline_opens_new_round(self):
        order = self._order()
        inspection1 = order.x_fai_inspection_id
        for n in ('SN-R1-001', 'SN-R1-002'):
            serial = self._feed(order, n)
            order.leave_station(serial, 'ok')
        inspection1.line_ids._set_pass_values()
        inspection1.action_done()
        self.assertEqual(order.x_fai_state, 'passed')
        # 同单隔天再上线：新一轮、样本清零、历史留痕
        order.action_offline()
        from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
        gate = give_pick(self.env, order)
        order.action_online()
        gate.action_cancel()
        self.assertEqual(order.x_fai_state, 'in_progress')
        self.assertEqual(order.x_fai_round, 2)
        self.assertEqual(order.x_fai_sample_count, 0)
        self.assertEqual(len(order.x_fai_inspection_ids), 2)
        self.assertEqual(inspection1.state, 'done')

    def test_13_report_mode_not_triggered(self):
        order = self._order(mode='report')
        self.assertEqual(order.x_fai_state, 'none')

    # ---------------- R2 样本收集与投入限流 ----------------
    def test_20_sample_registration_and_gate(self):
        order = self._order()
        s1 = self._feed(order, 'SN-FAI-001')
        s2 = self._feed(order, 'SN-FAI-002')
        inspection = order.x_fai_inspection_id
        self.assertEqual(inspection.x_fai_serial_ids, s1 | s2)
        with self.assertRaises(ValidationError):
            self._feed(order, 'SN-FAI-003')
        self.assertEqual(order.x_fai_sample_count, 2)

    def test_21_ng_leave_releases_quota_no_rework_refill(self):
        order = self._order()
        inspection = order.x_fai_inspection_id
        s1 = self._feed(order, 'SN-FAI-101')
        s2 = self._feed(order, 'SN-FAI-102')
        self._ng(order, s2)
        self.assertNotIn(s2, inspection.x_fai_serial_ids)
        self.assertIn(s2, inspection.x_fai_removed_serial_ids)
        self.assertEqual(order.x_fai_sample_count, 1)
        # s2 维修回流复测（同站重扫）：放行进站但不再登记样本
        order.scan_enter('SN-FAI-102', self.wc_in)
        order.leave_station(s2, 'ok')
        self.assertNotIn(s2, inspection.x_fai_serial_ids)
        self.assertNotIn(s2, inspection.x_fai_arrived_serial_ids)
        # 名额已释放：新板可补位
        s3 = self._feed(order, 'SN-FAI-103')
        self.assertIn(s3, inspection.x_fai_serial_ids)

    def test_22_arrival_and_ready_activity(self):
        order = self._order()
        inspection = order.x_fai_inspection_id
        s1 = self._feed(order, 'SN-FAI-201')
        s2 = self._feed(order, 'SN-FAI-202')
        order.leave_station(s1, 'ok')
        self.assertEqual(order.x_fai_sample_done, 1)
        self.assertFalse(
            inspection.activity_ids.filtered(
                lambda a: a.summary == 'First article samples ready'))
        order.leave_station(s2, 'ok')
        self.assertEqual(order.x_fai_sample_done, 2)
        self.assertIn('First article samples ready',
                      inspection.activity_ids.mapped('summary'))

    # ---------------- R3+R4 判定联动 ----------------
    def test_30_pass_unlocks_feeding(self):
        order = self._order()
        inspection = order.x_fai_inspection_id
        for n in ('SN-FAI-301', 'SN-FAI-302'):
            serial = self._feed(order, n)
            order.leave_station(serial, 'ok')
        with self.assertRaises(ValidationError):
            self._feed(order, 'SN-FAI-303')
        inspection.line_ids._set_pass_values()
        inspection.action_done()
        self.assertEqual(order.x_fai_state, 'passed')
        self._feed(order, 'SN-FAI-303')

    def test_31_fail_opens_new_round(self):
        order = self._order()
        inspection = order.x_fai_inspection_id
        for n in ('SN-FAI-401', 'SN-FAI-402'):
            serial = self._feed(order, n)
            order.leave_station(serial, 'ok')
        inspection.line_ids[0].write(
            {'is_checked': True, 'manual_result': 'fail'})
        inspection.line_ids[1]._set_pass_values()
        inspection.action_done()
        self.assertEqual(inspection.state, 'done')
        self.assertNotEqual(inspection.result, 'pass')  # fail/partial 皆判退
        self.assertEqual(order.x_fai_state, 'in_progress')
        self.assertEqual(order.x_fai_round, 2)
        new = order.x_fai_inspection_id
        self.assertNotEqual(new, inspection)
        self.assertEqual(new.state, 'open')
        self.assertEqual(new.sample_size, 2)
        self.assertFalse(new.x_fai_serial_ids)
        # 限流保持：新一轮可投 2 台、第 3 台仍拦
        self._feed(order, 'SN-FAI-403')
        self._feed(order, 'SN-FAI-404')
        with self.assertRaises(ValidationError):
            self._feed(order, 'SN-FAI-405')

    def test_32_done_guards(self):
        order = self._order()
        inspection = order.x_fai_inspection_id
        # 样本未齐（只到位 1/2）且有 pending 行：两个守卫依次验证
        s1 = self._feed(order, 'SN-FAI-501')
        order.leave_station(s1, 'ok')
        with self.assertRaises(UserError):
            inspection.action_done()
        inspection.line_ids._set_pass_values()
        with self.assertRaises(UserError):
            inspection.action_done()  # 到位 1 < 2
        s2 = self._feed(order, 'SN-FAI-502')
        order.leave_station(s2, 'ok')
        inspection.action_done()  # 齐套+全过 → 通过
        self.assertEqual(inspection.result, 'pass')

    def test_33_gate_passes_without_fai(self):
        self.scheme.active = False
        order = self._order()
        for n in ('A', 'B', 'C'):
            self._feed(order, 'SN-NOFAI-%s' % n)
