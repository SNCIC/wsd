from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestReelEnd(TransactionCase):
    """reel-end-confirm（卷终确认/换卷归零）：

    换料/下料时人工确认旧卷已尽 → 卷（lot）标记卷终 + 损耗归属单；
    完工倒冲把该卷一次扣到归零（流水部分 + 「卷终损耗」标差额），
    归零连坐清掉该卷全部预留（含他 MO 分占）；未卷终卷行为不变；
    卷终卷禁止再上料；换料拒绝路径零状态变更；负差额扣到 0 封顶。
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wh = cls.env['stock.warehouse'].search([], limit=1)
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        # 线边挂主库之下（与 line-side-mo-reservation 测试同形态）
        cls.line_side = cls.env['stock.location'].create({
            'name': 'RE-LINE-SIDE', 'usage': 'internal',
            'location_id': cls.wh.lot_stock_id.id,
        })
        cls.workshop = cls.env['sn.mrp.workshop'].create({'name': 'RE-WS'})
        cls.workshop.component_location_id = cls.line_side.id
        cls.production_line = cls.env['sn.mrp.production.line'].create({
            'name': 'RE-LINE', 'workshop_id': cls.workshop.id,
            'company_id': cls.env.company.id,
        })
        cls.bom_workshop = cls.env['sn.mrp.workshop'].create({'name': 'RE-WS-BOM'})
        if cls.wh.manufacture_steps != 'mrp_one_step' and cls.wh.pbm_loc_id:
            cls.bom_workshop.component_location_id = cls.env['stock.location'].create({
                'name': 'RE-BOM-COMP', 'usage': 'internal',
                'location_id': cls.wh.pbm_loc_id.id,
            }).id
        cls.product_a = cls.env['product.product'].create({
            'name': 'RE-A', 'default_code': 'RE-A',
            'tracking': 'lot', 'is_storable': True,
        })
        cls.product_fg = cls.env['product.product'].create({
            'name': 'RE-FG', 'default_code': 'RE-FG',
            'x_board_side': 'single',
        })
        cls.bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.product_fg.product_tmpl_id.id,
            'product_id': cls.product_fg.id,
            'product_uom_id': cls.uom_unit.id,
            'product_qty': 1.0,
            'type': 'normal',
            'x_workshop_id': cls.bom_workshop.id,
            'bom_line_ids': [(0, 0, {
                'product_id': cls.product_a.id,
                'product_qty': 2.0,
                'product_uom_id': cls.uom_unit.id,
            })],
        })
        cls.workcenter = cls.env['mrp.workcenter'].create({'name': 'RE-WC'})
        cls.op = cls.env['sn.wsd.operation'].create({
            'name': 'RE-OP', 'code': 'RE-OP', 'x_station_type': 'assembly',
        })
        cls.service = cls.env['sn.smt.loading.service']

    @classmethod
    def _lot(cls, name, qty, location):
        lot = cls.env['stock.lot'].create({
            'name': name, 'product_id': cls.product_a.id,
            'company_id': cls.env.company.id,
        })
        cls.env['stock.quant'].create({
            'product_id': cls.product_a.id,
            'location_id': location.id,
            'lot_id': lot.id,
            'quantity': qty,
        })
        return lot

    @classmethod
    def _make_order(cls, planned_qty, mo_qty=500):
        MesOrder = cls.env['sn.wsd.mes.order']
        production = cls.env['mrp.production'].create({
            'product_id': cls.product_fg.id,
            'product_qty': mo_qty,
            'bom_id': cls.bom.id,
        })
        with patch.object(type(MesOrder), '_setup_route', lambda self: True):
            order = MesOrder.create({
                'production_id': production.id,
                'production_line_id': cls.production_line.id,
                'date_plan': fields.Date.today(),
                'planned_qty': planned_qty,
            })
        cls.env['sn.smt.online.material'].create({
            'mes_order_id': order.id,
            'model_code': 'RE-FG',
            'device_seq': 1,
            'table_no': 'T1',
            'loadpoint': '25',
            'item_code': 'RE-A',
            'process_face': 'single',
            'point_qty': 4,
        })
        mes_route = cls.env['sn.wsd.mes.order.route'].create({
            'mes_order_id': order.id,
        })
        cls.env['sn.wsd.mes.order.route.operation'].create({
            'mes_route_id': mes_route.id,
            'mes_order_id': order.id,
            'operation_id': cls.op.id,
            'company_id': cls.env.company.id,
        })
        return order

    def _row(self, order):
        return order.x_smt_online_material_ids.filtered(
            lambda line: line.loadpoint == '25')[:1]

    def _flow(self, order, lot, qty):
        """直接造一条消耗流水（模拟过站扣点，按 SN 记录）。"""
        identity = self.env['sn.wsd.serial.identity'].generate_for_production(
            order.production_id, origin_type='manual')
        return self.env['sn.smt.material.consumption'].create({
            'serial_identity_id': identity.id,
            'route_operation_id': order.x_route_operation_ids[:1].id,
            'mes_order_id': order.id,
            'online_material_id': self._row(order).id,
            'material_lot_id': lot.id,
            'actual_product_id': self.product_a.id,
            'point_qty': qty,
            'product_qty': 1.0,
            'consumed_qty': qty,
            'qty_before': qty,
            'qty_after': 0.0,
            'consumed_at': fields.Datetime.now(),
        })

    def _line_side_quant(self, lot):
        return self.env['stock.quant'].search([
            ('product_id', '=', self.product_a.id),
            ('location_id', '=', self.line_side.id),
            ('lot_id', '=', lot.id),
        ])

    def _consume_moves(self, moves, lot):
        return moves.filtered(
            lambda m: m.product_id == self.product_a
            and any(ml.lot_id == lot for ml in m.move_line_ids))

    # --- A1: 换料确认已尽 → 旧卷标记 + 归属单 ---
    def test_change_material_reel_end_marks_old_lot(self):
        order = self._make_order(10)
        lot1 = self._lot('RE-LOT-1', 100, self.wh.lot_stock_id)
        lot2 = self._lot('RE-LOT-2', 100, self.wh.lot_stock_id)
        self.service.load_material(order, self.workcenter, '1.T1', '25', lot1.name)
        self.service.change_material(
            order, self.workcenter, '1.T1', '25', lot2.name, reel_end=True)
        self.assertTrue(lot1.x_reel_end, 'old reel must be flagged reel-end')
        self.assertEqual(lot1.x_reel_end_order_id, order)
        self.assertFalse(lot2.x_reel_end)

    # --- A1: 确认还有料 → 零变更 ---
    def test_change_material_without_reel_end_keeps_clean(self):
        order = self._make_order(10)
        lot1 = self._lot('RE-LOT-3', 100, self.wh.lot_stock_id)
        lot2 = self._lot('RE-LOT-4', 100, self.wh.lot_stock_id)
        self.service.load_material(order, self.workcenter, '1.T1', '25', lot1.name)
        self.service.change_material(
            order, self.workcenter, '1.T1', '25', lot2.name, reel_end=False)
        self.assertFalse(lot1.x_reel_end)
        self.assertFalse(lot1.x_reel_end_order_id)
        self.assertEqual(self._row(order).loaded_material_lot_id, lot2)

    # --- A6: 换料拒绝路径零状态变更（原子性不回归） ---
    def test_change_material_rejection_marks_nothing(self):
        order = self._make_order(10)
        lot1 = self._lot('RE-LOT-5', 100, self.wh.lot_stock_id)
        self.service.load_material(order, self.workcenter, '1.T1', '25', lot1.name)
        with self.assertRaises(UserError):
            self.service.change_material(
                order, self.workcenter, '1.T1', '25', 'NO-SUCH-SN', reel_end=True)
        self.assertFalse(lot1.x_reel_end, 'rejected change must not flag the old reel')
        row = self._row(order)
        self.assertEqual(row.is_load, 'Y', 'old reel stays online')
        self.assertEqual(row.loaded_material_lot_id, lot1)

    # --- A1: 单独下料确认已尽 → 标记 ---
    def test_unload_reel_end_marks_lot(self):
        order = self._make_order(10)
        lot1 = self._lot('RE-LOT-6', 100, self.wh.lot_stock_id)
        self.service.load_material(order, self.workcenter, '1.T1', '25', lot1.name)
        self.service.unload(
            order, scope='station', device_table='1.T1', loadpoint='25',
            reel_end=True)
        self.assertTrue(lot1.x_reel_end)
        self.assertEqual(lot1.x_reel_end_order_id, order)

    # --- A5: 卷终卷禁止再上料 ---
    def test_load_blocked_for_reel_end_lot(self):
        order = self._make_order(10)
        lot1 = self._lot('RE-LOT-7', 100, self.wh.lot_stock_id)
        lot1.write({'x_reel_end': True, 'x_reel_end_order_id': order.id})
        with self.assertRaises(ValidationError) as ctx:
            self.service.load_material(order, self.workcenter, '1.T1', '25', lot1.name)
        self.assertIn('used up', str(ctx.exception))

    # --- A2: 卷终后第一次完工倒冲一次扣到归零（流水 + 卷终损耗） ---
    def test_backflush_reel_end_zeroes_book(self):
        order = self._make_order(500)
        lot1 = self._lot('RE-LOT-B1', 1000, self.line_side)
        self._flow(order, lot1, 800)
        lot1.write({'x_reel_end': True, 'x_reel_end_order_id': order.id})
        moves = order._mes_backflush(500, flow_ratio=1.0)
        lot_moves = self._consume_moves(moves, lot1)
        self.assertAlmostEqual(sum(lot_moves.mapped('quantity')), 1000.0)
        loss_moves = lot_moves.filtered(
            lambda m: 'Reel end loss' in (m.description_picking_manual or ''))
        self.assertTrue(loss_moves, 'a reel-end loss move must exist')
        self.assertAlmostEqual(sum(loss_moves.mapped('quantity')), 200.0)
        quant = self._line_side_quant(lot1)
        self.assertAlmostEqual(quant.quantity, 0.0)
        self.assertAlmostEqual(quant.reserved_quantity, 0.0)

    # --- A4: 未卷终卷倒冲行为不变（流水净值 × 比例） ---
    def test_backflush_non_reel_end_unchanged(self):
        order = self._make_order(500)
        lot1 = self._lot('RE-LOT-B2', 1000, self.line_side)
        self._flow(order, lot1, 800)
        moves = order._mes_backflush(500, flow_ratio=1.0)
        lot_moves = self._consume_moves(moves, lot1)
        self.assertAlmostEqual(sum(lot_moves.mapped('quantity')), 800.0)
        self.assertFalse(any(
            'Reel end loss' in (m.description_picking_manual or '')
            for m in lot_moves))
        quant = self._line_side_quant(lot1)
        self.assertAlmostEqual(quant.quantity, 200.0)

    # --- A7: 流水净值 > 账面 → 扣到 0 封顶、不报错 ---
    def test_backflush_reel_end_caps_at_book(self):
        order = self._make_order(500)
        lot1 = self._lot('RE-LOT-B3', 1000, self.line_side)
        self._flow(order, lot1, 1200)
        lot1.write({'x_reel_end': True, 'x_reel_end_order_id': order.id})
        moves = order._mes_backflush(500, flow_ratio=1.0)
        lot_moves = self._consume_moves(moves, lot1)
        self.assertAlmostEqual(sum(lot_moves.mapped('quantity')), 1000.0)
        quant = self._line_side_quant(lot1)
        self.assertAlmostEqual(quant.quantity, 0.0)
        self.assertFalse(
            any(q.quantity < 0 for q in self.env['stock.quant'].search([
                ('product_id', '=', self.product_a.id)])),
            'no negative stock anywhere')

    # --- A3: 卷级归零连坐——他 MO 同卷分占预留一并清零、被吃单可补料 ---
    def test_backflush_reel_end_cross_mo_clears_reservations(self):
        # MO1 需求 800（qty 400 × 2/台）、MO2 需求 1000（qty 500 × 2/台），
        # 共享线边同一卷 1000：MO1 建留先占 800，MO2 只剩 200 可占
        order1 = self._make_order(400, mo_qty=400)
        order2 = self._make_order(100, mo_qty=500)
        self.assertNotEqual(order1.production_id, order2.production_id)
        lot1 = self._lot('RE-LOT-B4', 1000, self.line_side)
        # 依次建留（批次料领料验证走整卷带量，直连建留钩子构造分占）
        order1._mes_assign_mo_line_side()
        order2._mes_assign_mo_line_side()
        quant = self._line_side_quant(lot1)
        self.assertAlmostEqual(quant.quantity, 1000.0)
        self.assertAlmostEqual(quant.reserved_quantity, 1000.0,
                               msg='MO1 800 + MO2 200 share the same reel')
        reserved1 = order1._mes_own_line_side_reserved(self.product_a)
        reserved2 = order2._mes_own_line_side_reserved(self.product_a)
        self.assertAlmostEqual(reserved1, 800.0)
        self.assertAlmostEqual(reserved2, 200.0)
        # MO1 生产把整卷用光：流水 800 + 抛料 200，卷终确认归 MO1
        self._flow(order1, lot1, 800)
        lot1.write({'x_reel_end': True, 'x_reel_end_order_id': order1.id})
        moves = order1._mes_backflush(400, flow_ratio=1.0)
        self.assertAlmostEqual(sum(
            self._consume_moves(moves, lot1).mapped('quantity')), 1000.0)
        quant = self._line_side_quant(lot1)
        self.assertAlmostEqual(quant.quantity, 0.0)
        self.assertAlmostEqual(quant.reserved_quantity, 0.0,
                                msg='reel-end zeroing clears reservations of '
                                    'BOTH MOs sharing the reel')
        self.assertAlmostEqual(
            order2._mes_own_line_side_reserved(self.product_a), 0.0,
            msg='MO2 share on the reel is cleared by the co-zeroing')
        # MO2 的组件需求未满足（份额被吃）——补料出口可用
        raw2 = order2.production_id.move_raw_ids.filtered(
            lambda m: m.product_id == self.product_a)
        self.assertAlmostEqual(raw2.quantity, 0.0)
        order2.action_generate_over_picking(
            [{'product_id': self.product_a.id, 'qty': 200.0}],
            reason='reel-end cross-MO supplement')
        supplement = order2.picking_ids.filtered(
            lambda p: p.picking_type_id
            == self.wh.picking_type_over_pick_id)
        self.assertTrue(supplement)
