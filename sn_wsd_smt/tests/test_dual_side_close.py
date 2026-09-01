"""双面板 T 面单自动关结 + 完结（不入库）自身倒冲。

- 有消耗流水的按流水净值 × (过点板数−报废板数)/过点板数 扣，批次跟
  着上线扫描的卷走；报废板份额已由报废单扣过，不重复扣
- 没上流水的 BOM 本面行兜底（散料口径）
- 产出+报废 ≥ 排产 且无在制时，最后一扫自动完结（含倒冲）
- 没投满不自动关，手动按钮兜底；非 T 面单禁用手动完结
"""

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDualSideClose(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create(
            {'name': 'WS-DC', 'code': 'WSDC'})
        cls.line = cls.env['sn.mrp.production.line'].create(
            {'name': 'LDC', 'code': 'LDC', 'workshop_id': cls.workshop.id})
        cls.line_side = cls.env['stock.location'].create(
            {'name': 'DC-LINE-SIDE', 'usage': 'internal'})
        cls.workshop.component_location_id = cls.line_side.id

        Operation = cls.env['sn.wsd.operation']
        cls.op_t_in = Operation.create(
            {'name': 'DC T IN', 'code': 'DCTIN', 'x_station_type': 'assembly'})
        cls.op_t_out = Operation.create(
            {'name': 'DC T OUT', 'code': 'DCTOUT', 'x_station_type': 'final_test'})
        Route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True)
        cls.route_t = Route.create({
            'name': 'DC-RT-T', 'code': 'DCRTT',
            'x_workshop_id': cls.workshop.id,
            'x_production_side': 'top', 'state': 'confirmed',
            'route_operation_ids': [
                (0, 0, {'operation_id': cls.op_t_in.id, 'sequence': 10,
                        'x_allow_entry': True}),
                (0, 0, {'operation_id': cls.op_t_out.id, 'sequence': 20,
                        'x_allow_exit': True}),
            ],
            'x_daily_input_operation_id': cls.op_t_in.id,
            'x_daily_output_operation_id': cls.op_t_out.id,
            'x_workorder_input_operation_id': cls.op_t_in.id,
            'x_material_operation_id': cls.op_t_in.id,
        })
        route_ops = cls.route_t.route_operation_ids.sorted('sequence')
        route_ops[1].blocked_by_route_operation_ids = [(6, 0, route_ops[0].ids)]
        cls.env['sn.wsd.process.route.drawing'].create(
            {'route_id': cls.route_t.id, 'x_drawing_no': 'DWG-DC'})
        # 双面产品的 B 面路线也必须绑定，MO 校验才放行
        cls.op_b = Operation.create(
            {'name': 'DC B', 'code': 'DCB', 'x_station_type': 'assembly'})
        cls.route_b = Route.create({
            'name': 'DC-RT-B', 'code': 'DCRTB',
            'x_workshop_id': cls.workshop.id,
            'x_production_side': 'bottom', 'state': 'confirmed',
            'route_operation_ids': [
                (0, 0, {'operation_id': cls.op_b.id, 'sequence': 10,
                        'x_allow_entry': True, 'x_allow_exit': True}),
            ],
            'x_daily_input_operation_id': cls.op_b.id,
            'x_daily_output_operation_id': cls.op_b.id,
            'x_workorder_input_operation_id': cls.op_b.id,
        })
        cls.env['sn.wsd.process.route.drawing'].create(
            {'route_id': cls.route_b.id, 'x_drawing_no': 'DWG-DC'})

        # 双面成品 + 本面 BOM：T 面 = 批次电容2/板 + 散螺4/板
        cls.product = cls.env['product.product'].create({
            'name': 'P-DC', 'uom_id': cls.uom_unit.id, 'default_code': 'DWG-DC',
            'x_board_side': 'double', 'is_storable': True,
        })
        cls.cap = cls.env['product.product'].create({
            'name': 'DC CAP', 'uom_id': cls.uom_unit.id,
            'tracking': 'lot', 'is_storable': True,
        })
        cls.screw = cls.env['product.product'].create({
            'name': 'DC SCREW', 'uom_id': cls.uom_unit.id, 'is_storable': True,
        })
        cls.lot_cap = cls.env['stock.lot'].create({
            'name': 'DC-LOT-CAP', 'product_id': cls.cap.id,
            'company_id': cls.company.id,
        })
        cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.product.product_tmpl_id.id,
            'product_id': cls.product.id,
            'product_uom_id': cls.uom_unit.id,
            'product_qty': 1.0, 'type': 'normal',
            'bom_line_ids': [
                (0, 0, {'product_id': cls.cap.id, 'product_qty': 2.0,
                        'product_uom_id': cls.uom_unit.id, 'x_board_side': 'top'}),
                (0, 0, {'product_id': cls.screw.id, 'product_qty': 4.0,
                        'product_uom_id': cls.uom_unit.id, 'x_board_side': 'top'}),
            ],
        })
        Quant = cls.env['stock.quant']
        Quant.create({'product_id': cls.cap.id, 'location_id': cls.line_side.id,
                      'lot_id': cls.lot_cap.id, 'quantity': 100.0})
        Quant.create({'product_id': cls.screw.id,
                      'location_id': cls.line_side.id, 'quantity': 100.0})

        # 单面板产品 + 路线：非 T 面单禁用完结（不入库）的对照
        cls.op_s = Operation.create(
            {'name': 'DC S', 'code': 'DCS', 'x_station_type': 'assembly'})
        cls.route_s = Route.create({
            'name': 'DC-RT-S', 'code': 'DCRTS',
            'x_workshop_id': cls.workshop.id,
            'x_production_side': 'single', 'state': 'confirmed',
            'route_operation_ids': [
                (0, 0, {'operation_id': cls.op_s.id, 'sequence': 10,
                        'x_allow_entry': True, 'x_allow_exit': True}),
            ],
            'x_daily_input_operation_id': cls.op_s.id,
            'x_daily_output_operation_id': cls.op_s.id,
            'x_workorder_input_operation_id': cls.op_s.id,
        })
        cls.env['sn.wsd.process.route.drawing'].create(
            {'route_id': cls.route_s.id, 'x_drawing_no': 'DWG-DC-S'})
        cls.product_s = cls.env['product.product'].create({
            'name': 'P-DC-S', 'uom_id': cls.uom_unit.id,
            'default_code': 'DWG-DC-S', 'x_board_side': 'single',
        })

        cls.wc_t_in = cls.env['mrp.workcenter'].create({
            'name': 'WC-DCTIN', 'x_workshop_id': cls.workshop.id,
            'x_operation_id': cls.op_t_in.id, 'x_production_line_id': cls.line.id,
        })
        cls.wc_t_out = cls.env['mrp.workcenter'].create({
            'name': 'WC-DCTOUT', 'x_workshop_id': cls.workshop.id,
            'x_operation_id': cls.op_t_out.id, 'x_production_line_id': cls.line.id,
        })
        cls.reason = cls.env['sn.wsd.scrap.reason'].search([], limit=1)
        if not cls.reason:
            cls.reason = cls.env['sn.wsd.scrap.reason'].create(
                {'name': 'DC scrap'})

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _make_order(self, qty=2, side='top'):
        product = self.product if side in ('top', 'bottom') else self.product_s
        mo = self.env['mrp.production'].create({
            'product_id': product.id,
            'product_qty': qty * 10,
            'company_id': self.company.id,
        })
        return self.env['sn.wsd.mes.order'].create({
            'production_id': mo.id,
            'production_line_id': self.line.id,
            'date_plan': fields.Date.today(),
            'planned_qty': qty,
            'x_side': side,
        })

    def _gate_online(self, order):
        from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
        picking = give_pick(self.env, order)
        order.action_online()
        picking.action_cancel()
        return order

    def _load_feeder(self, order, point_qty=2.0):
        """上线一张料站表行（电容卷）：过站内核在物料关联工序自动扣点。"""
        return self.env['sn.smt.online.material'].create({
            'mes_order_id': order.id, 'source': 'smt_table',
            'model_code': 'DCMOD', 'device_seq': 1, 'table_no': 'T1',
            'loadpoint': '01', 'item_code': self.cap.default_code,
            'process_face': 'top', 'is_load': 'Y',
            'loaded_material_lot_id': self.lot_cap.id,
            'loaded_qty': 50.0, 'point_qty': point_qty,
        })

    def _walk(self, order, sn_name, result='ok', scrap_reason=False):
        """一块板走完 T 面全程；扣点在投入扫描时由内核自动落账。"""
        serial = order.scan_enter(sn_name, self.wc_t_in)
        order.leave_station(serial, 'ok')
        order.scan_enter(sn_name, self.wc_t_out)
        order.leave_station(serial, result, scrap_reason=scrap_reason)
        return serial

    def _line_qty(self, product, lot=False):
        domain = [('product_id', '=', product.id),
                  ('location_id', '=', self.line_side.id)]
        if lot:
            domain.append(('lot_id', '=', lot.id))
        groups = self.env['stock.quant']._read_group(
            domain, groupby=[], aggregates=['quantity:sum'])
        return (groups[0][0] or 0.0) if groups else 0.0

    # ------------------------------------------------------------------
    # 自动关结：最后一扫即完结并倒冲
    # ------------------------------------------------------------------
    def test_01_auto_close_backflushes_flows_and_bom(self):
        order = self._gate_online(self._make_order(qty=2))
        self.assertTrue(order.x_is_dual_side_non_final)
        self._load_feeder(order)
        self._walk(order, 'DC-SN-001')
        self.assertEqual(order.state, 'in_progress')
        self._walk(order, 'DC-SN-002')
        # 流水净值 4（两块板），无报废 → 全额扣；散料 BOM 兜底 2 板 × 4
        self.assertEqual(order.state, 'done')
        self.assertAlmostEqual(order.x_done_qty, 2.0)
        self.assertAlmostEqual(self._line_qty(self.cap, self.lot_cap), 96.0)
        self.assertAlmostEqual(self._line_qty(self.screw), 92.0)
        moves = self.env['stock.move'].search([
            ('origin', '=', order.name), ('state', '=', 'done'),
            ('product_id', 'in', (self.cap | self.screw).ids)])
        self.assertEqual(len(moves), 2)

    def test_02_scrap_share_not_double_deducted(self):
        order = self._gate_online(self._make_order(qty=2))
        self._load_feeder(order)
        self._walk(order, 'DC-SN-101', result='scrap',
                   scrap_reason=self.reason)
        self._walk(order, 'DC-SN-102')
        # 报废单：电容 2（流水批次）+ 螺丝 4；自动关结份额 (2-1)/2 →
        # 电容 4×0.5=2，散料按 1 板 → 螺丝 4
        self.assertEqual(order.state, 'done')
        self.assertAlmostEqual(self._line_qty(self.cap, self.lot_cap), 96.0)
        self.assertAlmostEqual(self._line_qty(self.screw), 92.0)

    def test_03_underfed_not_auto_closed_manual_button_closes(self):
        order = self._gate_online(self._make_order(qty=2))
        self._load_feeder(order)
        self._walk(order, 'DC-SN-201')
        self.assertEqual(order.state, 'in_progress')
        order.action_close()
        self.assertEqual(order.state, 'done')
        self.assertAlmostEqual(self._line_qty(self.cap, self.lot_cap), 98.0)
        self.assertAlmostEqual(self._line_qty(self.screw), 96.0)

    def test_04_close_rejected_for_non_dual_order(self):
        # 单面板单：完结（不入库）不可用，必须走完工入库
        order = self._gate_online(self._make_order(qty=1, side='single'))
        self.assertFalse(order.x_is_dual_side_non_final)
        with self.assertRaises(ValidationError):
            order.action_close()

    def test_05_close_blocked_by_shortage(self):
        # 线边没料：倒冲硬拦，完结整体回滚（与完工入库同口径）
        self.env['stock.quant'].search([
            ('location_id', '=', self.line_side.id)]).unlink()
        order = self._gate_online(self._make_order(qty=1))
        serial = order.scan_enter('DC-SN-301', self.wc_t_in)
        order.leave_station(serial, 'ok')
        order.scan_enter('DC-SN-301', self.wc_t_out)
        with self.assertRaises(ValidationError):
            order.leave_station(serial, 'ok')  # 自动关结里的倒冲失败
        self.env.flush_all()
        order.invalidate_recordset()
        self.assertEqual(order.state, 'in_progress')

    def test_06_auto_close_skipped_while_wip_remains(self):
        # 排产 1：板停在 AOI（WIP）未流出 → 不自动关；流出那一扫才关
        order = self._gate_online(self._make_order(qty=1))
        self._load_feeder(order)
        serial = order.scan_enter('DC-SN-401', self.wc_t_in)
        order.leave_station(serial, 'ok')
        order.scan_enter('DC-SN-401', self.wc_t_out)
        self.assertEqual(order.state, 'in_progress')
        order.leave_station(serial, 'ok')
        self.assertEqual(order.state, 'done')
