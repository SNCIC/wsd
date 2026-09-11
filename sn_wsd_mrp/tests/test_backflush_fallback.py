from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBackflushFallback(TransactionCase):
    """backflush-tracked-bom-fallback：批次组件无流水按 BOM 兜底倒扣——
    不再硬拦、批次按拣料策略分配（FEFO 跨批拆行）、兜底 move 打标、
    线边不足仍整单回滚、面别过滤不变。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create({
            'name': 'WS-BFFB', 'code': 'WBFB'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'BFFB', 'code': 'BFB', 'workshop_id': cls.workshop.id,
        })
        cls.line_side = cls.env['stock.location'].create({
            'name': 'BFFB-LINE', 'usage': 'internal'})
        cls.workshop.component_location_id = cls.line_side.id
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-BFFB', 'code': 'RTBFB',
                'x_workshop_id': cls.workshop.id,
            })
        Operation = cls.env['sn.wsd.operation']
        cls.op_in = Operation.create({
            'name': 'BFFB-IN', 'code': 'BIN', 'x_station_type': 'assembly'})
        cls.op_out = Operation.create({
            'name': 'BFFB-OUT', 'code': 'BOUT', 'x_station_type': 'final_test'})
        cls.route.write({
            'state': 'confirmed',
            'x_production_side': 'single',
            'route_operation_ids': [
                (0, 0, {'operation_id': cls.op_in.id, 'sequence': 10}),
                (0, 0, {'operation_id': cls.op_out.id, 'sequence': 20}),
            ],
            'x_daily_input_operation_id': cls.op_in.id,
            'x_daily_output_operation_id': cls.op_out.id,
            'x_workorder_input_operation_id': cls.op_in.id,
        })
        cls.env['sn.wsd.process.route.drawing'].create({
            'route_id': cls.route.id, 'x_drawing_no': 'DWG-BFFB'})

    # ------------------------------------------------------------------
    # fixtures
    # ------------------------------------------------------------------

    def _lot(self, product, name, removal_date=False):
        vals = {'name': name, 'product_id': product.id,
                'company_id': self.company.id}
        if removal_date:
            vals['removal_date'] = removal_date
        return self.env['stock.lot'].create(vals)

    def _put_stock(self, product, lot, qty):
        self.env['stock.quant'].create({
            'product_id': product.id,
            'location_id': self.line_side.id,
            'lot_id': lot.id if lot else False,
            'quantity': qty,
        })

    def _order(self, bom_lines, bom_qty=10.0):
        """MO + BOM（bom_lines: [(product, qty_per_bom, side)]）+ 制令单。"""
        product = self.env['product.product'].create({
            'name': 'P-BFFB', 'uom_id': self.uom_unit.id,
            'default_code': 'DWG-BFFB', 'x_board_side': 'single',
        })
        bom = self.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id,
            'product_id': product.id,
            'product_uom_id': self.uom_unit.id,
            'product_qty': bom_qty,
            'type': 'normal',
            'x_workshop_id': self.workshop.id,
            'bom_line_ids': [(0, 0, {
                'product_id': comp.id,
                'product_qty': qty,
                'product_uom_id': self.uom_unit.id,
                'x_board_side': side,
            }) for comp, qty, side in bom_lines],
        })
        mo = self.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': bom_qty,
            'bom_id': bom.id, 'company_id': self.company.id,
        })
        return self.env['sn.wsd.mes.order'].create({
            'production_id': mo.id,
            'production_line_id': self.line.id,
            'date_plan': fields.Date.today(),
            'planned_qty': bom_qty,
        })

    def _component(self, name, tracking='lot'):
        return self.env['product.product'].create({
            'name': name, 'uom_id': self.uom_unit.id,
            'is_storable': True, 'tracking': tracking,
        })

    def _fallback_moves(self, moves, product):
        return moves.filtered(lambda m: m.product_id == product)

    # ------------------------------------------------------------------
    # scenarios
    # ------------------------------------------------------------------

    def test_tracked_component_falls_back_with_marker(self):
        # spec: mes-backflush/spec/批次组件无流水按 BOM 兜底倒扣/批次组件无流水兜底
        # spec: mes-backflush/spec/批次组件无流水按 BOM 兜底倒扣/兜底扣减打标
        tracked = self._component('BFFB-CHIP')
        untracked = self._component('BFFB-SCREW', tracking='none')
        lot = self._lot(tracked, 'LOT-1')
        self._put_stock(tracked, lot, 20.0)
        self._put_stock(untracked, False, 20.0)
        order = self._order([(tracked, 2.0, 'single'), (untracked, 3.0, 'single')])
        # 完工 5（BOM 10 → 比例 0.5）：芯片扣 1、螺丝扣 1.5，均不再硬拦
        moves = order._mes_backflush(5.0)
        chip_move = self._fallback_moves(moves, tracked)
        screw_move = self._fallback_moves(moves, untracked)
        self.assertEqual(len(chip_move), 1)
        self.assertAlmostEqual(chip_move.product_uom_qty, 1.0)
        self.assertEqual(chip_move.move_line_ids.lot_id, lot)
        self.assertAlmostEqual(chip_move.move_line_ids.quantity, 1.0)
        self.assertAlmostEqual(screw_move.product_uom_qty, 1.5)
        for move in chip_move | screw_move:
            self.assertIn('BOM fallback (no consumption flow)',
                          move.description_picking_manual)

    def test_fefo_split_across_lots(self):
        # spec: mes-backflush/spec/批次组件无流水按 BOM 兜底倒扣/兜底批次按拣料策略选取并跨批次拆行
        tracked = self._component('BFFB-CAP')
        lot_due = self._lot(tracked, 'LOT-DUE', removal_date='2026-01-01')
        lot_later = self._lot(tracked, 'LOT-LATER', removal_date='2027-01-01')
        self._put_stock(tracked, lot_due, 0.6)
        self._put_stock(tracked, lot_later, 5.0)
        order = self._order([(tracked, 2.0, 'single')])
        moves = order._mes_backflush(5.0)  # 需扣 1.0
        lines = moves.filtered(
            lambda m: m.product_id == tracked).move_line_ids.sorted('id')
        self.assertEqual(len(lines), 2, 'single lot falls short -> split')
        self.assertEqual(lines.mapped('lot_id'), lot_due | lot_later)
        # FEFO：先到期批次在前，补足剩余
        self.assertEqual(lines[0].lot_id, lot_due)
        self.assertAlmostEqual(lines[0].quantity, 0.6)
        self.assertAlmostEqual(lines[1].quantity, 0.4)
        self.assertAlmostEqual(sum(lines.mapped('quantity')), 1.0)

    def test_shortage_still_rolls_back(self):
        # spec: mes-backflush/spec/批次组件无流水按 BOM 兜底倒扣/线边不足仍整单回滚
        tracked = self._component('BFFB-EMPTY')
        order = self._order([(tracked, 2.0, 'single')])
        with self.assertRaises(ValidationError) as ctx:
            order._mes_backflush(5.0)
        self.assertIn('Line-side stock', str(ctx.exception))

    def test_side_filter_unchanged(self):
        # spec: mes-backflush/spec/批次组件无流水按 BOM 兜底倒扣/面别过滤不变
        single_comp = self._component('BFFB-SINGLE')
        top_comp = self._component('BFFB-TOP')
        lot_s = self._lot(single_comp, 'LOT-S')
        lot_t = self._lot(top_comp, 'LOT-T')
        self._put_stock(single_comp, lot_s, 20.0)
        self._put_stock(top_comp, lot_t, 20.0)
        # 单面单只扣 single 行；top 行不属于本面
        order = self._order([
            (single_comp, 2.0, 'single'), (top_comp, 4.0, 'top')])
        moves = order._mes_backflush(10.0)
        self.assertTrue(self._fallback_moves(moves, single_comp))
        self.assertFalse(self._fallback_moves(moves, top_comp))
