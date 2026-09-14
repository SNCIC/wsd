from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestStationFeedQuota(TransactionCase):
    """投入台数上限：过站模式按 SN 去重的累计投入不得超过排产数量。
    拦的只是"下一台新板"（首次投入）；已投入板的复测/维修回流不受影响。
    报废占额（与报工配额同口径：报废消耗额度、不释放）；清除过站把板
    拉回"从未投入"，额度随之释放。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create({
            'name': 'WS-FEEDQ', 'code': 'WFQ'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'FEEDQ', 'code': 'FDQ', 'workshop_id': cls.workshop.id,
        })
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-FEEDQ', 'code': 'RTFDQ',
                'x_workshop_id': cls.workshop.id,
            })
        Operation = cls.env['sn.wsd.operation']
        cls.op_a = Operation.create({
            'name': 'FQ-A', 'code': 'FQA', 'x_station_type': 'assembly',
            'x_max_test_count': 9})
        cls.op_b = Operation.create({
            'name': 'FQ-B', 'code': 'FQB', 'x_station_type': 'final_test',
            'x_max_test_count': 3})
        cls.op_c = Operation.create({
            'name': 'FQ-C', 'code': 'FQC', 'x_station_type': 'final_test',
            'x_max_test_count': 3})
        cls.route.write({
            'state': 'confirmed',
            'x_production_side': 'single',
            'route_operation_ids': [
                (0, 0, {'operation_id': cls.op_a.id, 'sequence': 10}),
                (0, 0, {'operation_id': cls.op_b.id, 'sequence': 20}),
                (0, 0, {'operation_id': cls.op_c.id, 'sequence': 30}),
            ],
            'x_daily_input_operation_id': cls.op_a.id,
            'x_daily_output_operation_id': cls.op_b.id,
            'x_workorder_input_operation_id': cls.op_a.id,
        })
        cls.env['sn.wsd.process.route.drawing'].create({
            'route_id': cls.route.id, 'x_drawing_no': 'DWG-FEEDQ'})
        route_ops = cls.route.route_operation_ids.sorted('sequence')
        route_ops[0].x_allow_entry = True
        route_ops[2].x_allow_exit = True
        route_ops[1].blocked_by_route_operation_ids = [(6, 0, route_ops[0].ids)]
        route_ops[2].blocked_by_route_operation_ids = [(6, 0, route_ops[1].ids)]
        cls.defect_code = cls.env['sn.wsd.quality.defect.code'].search(
            [('company_id', 'in', [cls.company.id, False])], limit=1)
        if not cls.defect_code:
            cls.defect_code = cls.env['sn.wsd.quality.defect.code'].create({
                'name': 'FEEDQ Defect', 'code': 'FQD',
                'category': 'other', 'severity': 'minor',
            })
        cls.scrap_reason = cls.env['sn.wsd.scrap.reason'].search(
            [('company_id', 'in', [cls.company.id, False])], limit=1)
        if not cls.scrap_reason:
            cls.scrap_reason = cls.env['sn.wsd.scrap.reason'].create({
                'name': 'FEEDQ Scrap', 'code': 'FQSCR'})

    # ------------------------------------------------------------------
    # fixtures
    # ------------------------------------------------------------------

    def _make_order_online(self, qty=2, product=False):
        if not product:
            product = self.env['product.product'].create({
                'name': 'P-FEEDQ', 'uom_id': self.uom_unit.id,
                'default_code': 'DWG-FEEDQ', 'x_board_side': 'single',
            })
        mo = self.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': max(10, qty),
            'bom_id': product.bom_ids[:1].id if product.bom_ids else False,
            'company_id': self.company.id,
        })
        order = self.env['sn.wsd.mes.order'].create({
            'production_id': mo.id,
            'production_line_id': self.line.id,
            'date_plan': fields.Date.today(),
            'planned_qty': qty,
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

    def _feed_ok(self, order, wc, sn_name):
        serial = order.scan_enter(sn_name, wc)
        order.leave_station(serial, 'ok')
        return serial

    # ------------------------------------------------------------------
    # 台数上限：拦下一台新板
    # ------------------------------------------------------------------

    def test_feed_capped_at_planned_qty(self):
        order = self._make_order_online(qty=2)
        wcs = self._wcs()
        self._feed_ok(order, wcs['a'], 'SN-FQ-001')
        self._feed_ok(order, wcs['a'], 'SN-FQ-002')
        # 已投 2 台=排产 2：第 3 台新板被拦，报错带排产数量口径
        with self.assertRaises(ValidationError) as exc:
            order.scan_enter('SN-FQ-003', wcs['a'])
        self.assertIn('scheduled quantity', str(exc.exception))
        self.assertEqual(order.x_input_qty, 2.0)

    def test_reentry_at_cap_not_blocked(self):
        # 满额后已投入板的复测不受限（拦的只是新板投入）
        order = self._make_order_online(qty=1)
        wcs = self._wcs()
        serial = self._feed_ok(order, wcs['a'], 'SN-FQ-101')
        with self.assertRaises(ValidationError):
            order.scan_enter('SN-FQ-102', wcs['a'])
        # SN-101 复过 B（首过 NG 再进站复测）不受台数上限影响
        order.scan_enter('SN-FQ-101', wcs['b'])
        order.leave_station(serial, 'ng', ng_defect=self.defect_code)
        order.scan_enter('SN-FQ-101', wcs['b'])
        order.leave_station(serial, 'ok')

    def test_scrap_consumes_quota(self):
        # 报废占额不释放（与报工配额同口径）：排产 2 = 报废 1 + 在制 1，
        # 第 3 台仍被拦。报废链需要 BOM 与线边库位（同 ledger 报废夹具）
        self.workshop.component_location_id = self.env['stock.location'].create({
            'name': 'FEEDQ-LINE', 'usage': 'internal',
        })
        component = self.env['product.product'].create({
            'name': 'FEEDQ-COMP', 'uom_id': self.uom_unit.id,
            'is_storable': True,
        })
        scrap_product = self.env['product.product'].create({
            'name': 'P-FEEDQ-SCRAP', 'uom_id': self.uom_unit.id,
            'default_code': 'DWG-FEEDQ', 'x_board_side': 'single',
        })
        self.env['mrp.bom'].create({
            'product_tmpl_id': scrap_product.product_tmpl_id.id,
            'product_id': scrap_product.id,
            'product_uom_id': self.uom_unit.id,
            'product_qty': 1.0,
            'type': 'normal',
            'x_workshop_id': self.workshop.id,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id,
                'product_qty': 2.0,
                'product_uom_id': self.uom_unit.id,
            })],
        })
        order = self._make_order_online(qty=2, product=scrap_product)
        wcs = self._wcs()
        scrapped = order.scan_enter('SN-FQ-201', wcs['a'])
        order.leave_station(scrapped, 'scrap', scrap_reason=self.scrap_reason)
        self._feed_ok(order, wcs['a'], 'SN-FQ-202')
        with self.assertRaises(ValidationError):
            order.scan_enter('SN-FQ-203', wcs['a'])

    def test_clear_station_pass_frees_quota(self):
        # 清除过站=回到"从未投入"，额度随之释放（计数口径=历史行）
        order = self._make_order_online(qty=2)
        wcs = self._wcs()
        self._feed_ok(order, wcs['a'], 'SN-FQ-301')
        serial2 = self._feed_ok(order, wcs['a'], 'SN-FQ-302')
        with self.assertRaises(ValidationError):
            order.scan_enter('SN-FQ-303', wcs['a'])
        order.action_clear_station_pass(serial2)
        self._feed_ok(order, wcs['a'], 'SN-FQ-303')
