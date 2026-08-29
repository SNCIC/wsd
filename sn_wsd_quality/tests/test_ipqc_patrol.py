from psycopg2 import IntegrityError

from odoo import fields
from odoo.tests import Form, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestIpqcPatrol(TransactionCase):
    """过程巡检 IPQC·定时巡检+异常驱动样本录入（add-mes-ipqc-patrol）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create(
            {'name': 'WS-IPQC', 'code': 'WSIP'})
        cls.line_a = cls.env['sn.mrp.production.line'].create({
            'name': 'LIPA', 'code': 'LIPA', 'workshop_id': cls.workshop.id,
        })
        cls.line_b = cls.env['sn.mrp.production.line'].create({
            'name': 'LIPB', 'code': 'LIPB', 'workshop_id': cls.workshop.id,
        })
        cls.workshop.component_location_id = cls.env['stock.location'].create(
            {'name': 'LINESIDE-IPQC', 'usage': 'internal'}).id
        Operation = cls.env['sn.wsd.operation']
        cls.op_in = Operation.create({
            'name': 'IP-IN', 'code': 'IPIN', 'x_station_type': 'assembly',
            'x_max_test_count': 3,
        })
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-IPQC', 'code': 'RTIP', 'x_workshop_id': cls.workshop.id,
            })
        cls.route.write({
            'state': 'confirmed', 'x_production_side': 'single',
            'route_operation_ids': [
                (0, 0, {'operation_id': cls.op_in.id, 'sequence': 10,
                        'x_allow_entry': True}),
            ],
            'x_daily_input_operation_id': cls.op_in.id,
            'x_daily_output_operation_id': cls.op_in.id,
            'x_workorder_input_operation_id': cls.op_in.id,
        })
        cls.env['sn.wsd.process.route.drawing'].create(
            {'route_id': cls.route.id, 'x_drawing_no': 'DWG-IPQC-TEST'})
        cls.product = cls.env['product.product'].create({
            'name': 'P-IPQC', 'uom_id': cls.uom_unit.id,
            'default_code': 'DWG-IPQC-TEST', 'x_board_side': 'single',
        })
        component = cls.env['product.product'].create({
            'name': 'COMP-IPQC', 'uom_id': cls.uom_unit.id, 'is_storable': True,
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
            'product_id': cls.product.id, 'product_qty': 50,
            'company_id': cls.company.id,
        })
        cls.scheme = cls.env['sn.wsd.quality.inspection.scheme'].create({
            'name': 'IPQC SCHEME', 'code': 'IPQC-01',
            'inspection_type': 'ipqc', 'state': 'effective',
            'operation_id': cls.op_in.id,
            'interval_minutes': 120, 'sample_size': 3,
            'line_ids': [
                (0, 0, {'name': 'Paste thickness', 'item_code': 'IPQC-PST',
                        'item_type': 'numeric', 'lower_limit': 0.1,
                        'upper_limit': 0.2}),
                (0, 0, {'name': 'Reflow temp', 'item_code': 'IPQC-RFT',
                        'item_type': 'numeric', 'lower_limit': 235.0,
                        'upper_limit': 245.0}),
            ],
        })
        # 缺陷码：一板多不良时按缺陷码区分多行
        cls.defect_a = cls.env['sn.wsd.quality.defect.code'].create({
            'name': 'IPQC Defect A', 'code': 'IPQC-DGA',
            'category': 'other', 'severity': 'minor',
        })
        cls.defect_b = cls.env['sn.wsd.quality.defect.code'].create({
            'name': 'IPQC Defect B', 'code': 'IPQC-DGB',
            'category': 'other', 'severity': 'major',
        })

    def _order(self, line, qty=20):
        order = self.env['sn.wsd.mes.order'].create({
            'production_id': self.mo.id, 'production_line_id': line.id,
            'date_plan': fields.Date.today(), 'planned_qty': qty,
        })
        from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
        gate = give_pick(self.env, order)
        order.action_online()
        gate.action_cancel()
        return order

    def _wc(self, line):
        return self.env['mrp.workcenter'].create({
            'name': 'WC-IPQC-%s' % line.code, 'x_workshop_id': self.workshop.id,
            'x_production_line_id': line.id, 'x_operation_id': self.op_in.id,
        })

    def _make_activity(self, order, wc, name):
        serial = order.scan_enter(name, wc)
        order.leave_station(serial, 'ok')
        return serial

    def _inspection(self):
        # 巡检单按方案建（cron 同口径）：预填抽样数量、不预建样本行
        return self.env['sn.wsd.quality.inspection'].create_from_scheme(
            self.scheme, {'production_line_id': self.line_a.id})

    # ---------------- V0 手动巡检 ----------------
    def test_10_manual_inspection_brings_scheme_lines(self):
        inspection = self.env['sn.wsd.quality.inspection'].new({
            'inspection_type': 'ipqc',
        })
        inspection.scheme_id = self.scheme
        inspection._onchange_scheme_id()  # UI 中由 onchange 触发，测试直调
        self.assertEqual(len(inspection.line_ids), 2,
                         'onchange brings scheme template lines')
        self.assertEqual(inspection.sample_size, 3)
        self.assertEqual(inspection.x_picked_qty, 3,
                         'picking the scheme pre-fills the picked qty')

    def test_11_zero_defect_zero_entry(self):
        # 异常驱动：无不良零录入——不建任何样本行，统计只看抽样数量
        inspection = self._inspection()
        self.assertFalse(inspection.sample_ids,
                         'no defect found means no sample rows at all')
        self.assertEqual(inspection.x_picked_qty, 3,
                         'creating from the scheme pre-fills the picked qty')
        inspection.invalidate_recordset()
        self.assertEqual(inspection.sample_checked_qty, 3,
                         'checked defaults to the scheme sample size')
        self.assertEqual(inspection.sample_defect_qty, 0)
        inspection.write({'x_picked_qty': 5})
        inspection.invalidate_recordset()
        self.assertEqual(inspection.sample_checked_qty, 5,
                         'checked follows the picked qty')

    # ---------------- V1 定时引擎 ----------------
    def test_20_due_with_activity_creates_inspection(self):
        order = self._order(self.line_a)
        wc = self._wc(self.line_a)
        self._make_activity(order, wc, 'SN-IPQC-101')
        self.scheme._ipqc_patrol_tick()
        inspection = self.env['sn.wsd.quality.inspection'].search([
            ('inspection_type', '=', 'ipqc'),
            ('scheme_id', '=', self.scheme.id),
            ('production_line_id', '=', self.line_a.id),
        ], limit=1)
        self.assertTrue(inspection, 'due + activity opens a patrol inspection')
        self.assertEqual(inspection.state, 'open')
        self.assertEqual(len(inspection.line_ids), 2)
        self.assertIn('Patrol inspection due',
                      inspection.activity_ids.mapped('summary'))

    def test_21_no_activity_no_inspection(self):
        # 无任何产出活动（不建单不过站）→ 到期也不开单
        self.scheme._ipqc_patrol_tick()
        self.assertFalse(self.env['sn.wsd.quality.inspection'].search([
            ('inspection_type', '=', 'ipqc'),
            ('scheme_id', '=', self.scheme.id),
        ]))

    def test_22_open_inspection_not_duplicated(self):
        order = self._order(self.line_a)
        wc = self._wc(self.line_a)
        self._make_activity(order, wc, 'SN-IPQC-201')
        self.scheme._ipqc_patrol_tick()
        self.scheme._ipqc_patrol_tick()  # 第二次 tick：有 open 单在等
        count = self.env['sn.wsd.quality.inspection'].search_count([
            ('inspection_type', '=', 'ipqc'),
            ('scheme_id', '=', self.scheme.id),
            ('production_line_id', '=', self.line_a.id),
        ])
        self.assertEqual(count, 1, 'open inspection suppresses re-opening')

    def test_23_lineless_scheme_opens_per_active_line(self):
        # 方案未配产线：A/B 两线都有活动 → 各开一张
        order_a = self._order(self.line_a)
        order_b = self._order(self.line_b)
        wc_a, wc_b = self._wc(self.line_a), self._wc(self.line_b)
        self._make_activity(order_a, wc_a, 'SN-IPQC-301')
        self._make_activity(order_b, wc_b, 'SN-IPQC-302')
        self.scheme._ipqc_patrol_tick()
        lines_with = self.env['sn.wsd.quality.inspection'].search([
            ('inspection_type', '=', 'ipqc'),
            ('scheme_id', '=', self.scheme.id),
        ]).mapped('production_line_id')
        self.assertIn(self.line_a, lines_with)
        self.assertIn(self.line_b, lines_with)
        self.assertEqual(len(lines_with), 2)

    def test_24_report_mode_activity_counts(self):
        order = self.env['sn.wsd.mes.order'].create({
            'production_id': self.mo.id,
            'production_line_id': self.line_a.id,
            'date_plan': fields.Date.today(), 'planned_qty': 20,
            'x_manage_mode': 'report',  # 上线前设定（上线后锁定）
        })
        from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
        gate = give_pick(self.env, order)
        order.action_online()
        gate.action_cancel()
        op_row = order.x_route_operation_ids[:1]
        order.report_operation_qty(op_row, 5)
        self.scheme._ipqc_patrol_tick()
        inspection = self.env['sn.wsd.quality.inspection'].search([
            ('inspection_type', '=', 'ipqc'),
            ('scheme_id', '=', self.scheme.id),
            ('production_line_id', '=', self.line_a.id),
        ], limit=1)
        self.assertTrue(inspection, 'report-mode output counts as activity')

    def test_25_reminder_to_scheme_responsible(self):
        responsible = self.env['res.users'].create({
            'name': 'IPQC Responsible', 'login': 'ipqc.responsible',
        })
        self.scheme.responsible_user_id = responsible
        order = self._order(self.line_a)
        wc = self._wc(self.line_a)
        self._make_activity(order, wc, 'SN-IPQC-401')
        self.scheme._ipqc_patrol_tick()
        inspection = self.env['sn.wsd.quality.inspection'].search([
            ('inspection_type', '=', 'ipqc'),
            ('scheme_id', '=', self.scheme.id),
        ], limit=1)
        due = inspection.activity_ids.filtered(
            lambda a: a.summary == 'Patrol inspection due')
        self.assertEqual(due.user_id, responsible)

    # ---------------- V2 异常驱动样本录入 ----------------
    def test_30_scan_sn_auto_fail_onchange(self):
        # 扫板：样本行填 SN，pending 自动翻 fail（Form 触发 onchange）
        order = self._order(self.line_a)
        wc = self._wc(self.line_a)
        serial = self._make_activity(order, wc, 'SN-IPQC-501')
        inspection = self._inspection()
        with Form(inspection) as form:
            with form.sample_ids.new() as sample:
                sample.serial_identity_id = serial
        inspection.invalidate_recordset()
        self.assertEqual(inspection.sample_ids.serial_identity_id, serial)
        self.assertEqual(inspection.sample_ids.mapped('result'), ['fail'],
                         'filling the SN flips the pending sample to fail')

    def test_31_board_multiple_defects(self):
        # 一板多不良：同 SN 不同缺陷多行合法；同 SN 同缺陷被唯一约束拦截
        order = self._order(self.line_a)
        wc = self._wc(self.line_a)
        serial = self._make_activity(order, wc, 'SN-IPQC-601')
        inspection = self._inspection()
        Sample = self.env['sn.wsd.quality.inspection.sample']
        Sample.create({'inspection_id': inspection.id,
                       'serial_identity_id': serial.id,
                       'defect_code_id': self.defect_a.id, 'result': 'fail'})
        Sample.create({'inspection_id': inspection.id,
                       'serial_identity_id': serial.id,
                       'defect_code_id': self.defect_b.id, 'result': 'fail'})
        inspection.invalidate_recordset()
        self.assertEqual(len(inspection.sample_ids), 2,
                         'one board, two defect codes: two rows allowed')
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                Sample.create({'inspection_id': inspection.id,
                               'serial_identity_id': serial.id,
                               'defect_code_id': self.defect_a.id,
                               'result': 'fail'})

    def test_32_qty_rules(self):
        # 有 SN 行必须 qty=1；无 SN 行记缺陷数量且可修改
        order = self._order(self.line_a)
        wc = self._wc(self.line_a)
        serial = self._make_activity(order, wc, 'SN-IPQC-701')
        inspection = self._inspection()
        Sample = self.env['sn.wsd.quality.inspection.sample']
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                Sample.create({'inspection_id': inspection.id,
                               'serial_identity_id': serial.id,
                               'defect_code_id': self.defect_a.id,
                               'qty': 2, 'result': 'fail'})
        row = Sample.create({'inspection_id': inspection.id,
                             'defect_code_id': self.defect_b.id,
                             'qty': 3, 'result': 'fail'})
        self.assertEqual(row.qty, 3,
                         'SN-less rows carry the defect quantity')
        row.write({'qty': 2})
        self.assertEqual(row.qty, 2, 'the SN-less quantity stays editable')

    def test_33_stats_dedup_and_addition(self):
        # 统计纯加法、板级按 SN 去重：SN-A 两行只算一片，无 SN 行按 qty 累加
        order = self._order(self.line_a)
        wc = self._wc(self.line_a)
        sn_a = self._make_activity(order, wc, 'SN-IPQC-801')
        sn_b = self._make_activity(order, wc, 'SN-IPQC-802')
        inspection = self._inspection()
        inspection.write({'x_picked_qty': 8})
        Sample = self.env['sn.wsd.quality.inspection.sample']
        Sample.create({'inspection_id': inspection.id,
                       'serial_identity_id': sn_a.id,
                       'defect_code_id': self.defect_a.id, 'result': 'fail'})
        Sample.create({'inspection_id': inspection.id,
                       'serial_identity_id': sn_a.id,
                       'defect_code_id': self.defect_b.id, 'result': 'fail'})
        Sample.create({'inspection_id': inspection.id,
                       'serial_identity_id': sn_b.id,
                       'defect_code_id': self.defect_a.id, 'result': 'fail'})
        Sample.create({'inspection_id': inspection.id,
                       'defect_code_id': self.defect_b.id,
                       'qty': 3, 'result': 'fail'})
        inspection.invalidate_recordset()
        self.assertEqual(inspection.sample_defect_qty, 2 + 3,
                         'defect = distinct fail SNs (2) + SN-less qty (3)')
        self.assertEqual(inspection.sample_checked_qty, 8,
                         'checked = picked qty, not the sample row count')

    def test_34_history_lists_same_scope_inspections(self):
        # 历史页签：同产线×同工序的过往巡检（新到旧，不含自身）
        order = self._order(self.line_a)
        first = self.env['sn.wsd.quality.inspection'].create_from_scheme(
            self.scheme, {'production_line_id': self.line_a.id})
        first.action_start()
        first.line_ids._set_pass_values()
        first.action_done()
        inspection = self._inspection()
        history = inspection.x_ipqc_history_ids
        self.assertIn(first, history)
        self.assertNotIn(inspection, history)
        self.assertEqual(history[:1], first, 'newest first')
