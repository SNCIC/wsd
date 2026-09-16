from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSubstituteBackflush(TransactionCase):
    """substitute-rule R3：完工倒冲 / 报废 / MO 流水回填的替代覆盖判定
    走规则——完全替代不双扣不拦单、部分替代按实际流水、无规则维持
    BOM 兜底现状、被替代行报废落在在机替代料卷上。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create({
            'name': 'WS-SBF', 'code': 'WSBF'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'SBF', 'code': 'SBF', 'workshop_id': cls.workshop.id})
        cls.line_side = cls.env['stock.location'].create({
            'name': 'SBF-LINE', 'usage': 'internal'})
        cls.workshop.component_location_id = cls.line_side.id
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-SBF', 'code': 'RTSBF',
                'x_workshop_id': cls.workshop.id,
            })
        Operation = cls.env['sn.wsd.operation']
        cls.op = Operation.create({
            'name': 'SBF-OP', 'code': 'SBFOP', 'x_station_type': 'assembly'})
        cls.route.write({
            'state': 'confirmed',
            'x_production_side': 'single',
            'route_operation_ids': [
                (0, 0, {'operation_id': cls.op.id, 'sequence': 10}),
            ],
            'x_daily_input_operation_id': cls.op.id,
            'x_daily_output_operation_id': cls.op.id,
            'x_workorder_input_operation_id': cls.op.id,
        })
        cls.env['sn.wsd.process.route.drawing'].create({
            'route_id': cls.route.id, 'x_drawing_no': 'DWG-SBF'})
        cls.identity = cls.env['sn.wsd.serial.identity'].create({
            'name': 'SBF-SN-001', 'origin_type': 'manual'})
        cls.rule_model = cls.env['sn.wsd.substitute.rule']

    def _component(self, name):
        return self.env['product.product'].create({
            'name': name, 'default_code': name,
            'uom_id': self.uom_unit.id, 'is_storable': True,
            'tracking': 'lot',
        })

    def _lot(self, product, name):
        lot = self.env['stock.lot'].create({
            'name': name, 'product_id': product.id,
            'company_id': self.company.id})
        self.env['stock.quant'].create({
            'product_id': product.id,
            'location_id': self.line_side.id,
            'lot_id': lot.id,
            'quantity': 100.0,
        })
        return lot

    def _order(self, bom_lines, bom_qty=10.0):
        """MO + BOM + 制令单 + 私有路线 + 在线料行（A 类组件 1.T1/25）。"""
        product = self.env['product.product'].create({
            'name': 'P-SBF', 'default_code': 'DWG-SBF',
            'uom_id': self.uom_unit.id, 'x_board_side': 'single',
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
                'x_board_side': 'single',
            }) for comp, qty in bom_lines],
        })
        mo = self.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': bom_qty,
            'bom_id': bom.id, 'company_id': self.company.id,
        })
        MesOrder = self.env['sn.wsd.mes.order']
        with patch.object(type(MesOrder), '_setup_route', lambda self: True):
            order = MesOrder.create({
                'production_id': mo.id,
                'production_line_id': self.line.id,
                'date_plan': fields.Date.today(),
                'planned_qty': bom_qty,
            })
        private_route = self.env['sn.wsd.mes.order.route'].create({
            'mes_order_id': order.id, 'route_id': self.route.id})
        order.x_mes_route_id = private_route.id
        rop = self.env['sn.wsd.mes.order.route.operation'].create({
            'mes_route_id': private_route.id,
            'operation_id': self.op.id,
            'sequence': 10,
        })
        online = self.env['sn.smt.online.material'].create({
            'mes_order_id': order.id,
            'model_code': 'DWG-SBF',
            'device_seq': 1,
            'table_no': 'T1',
            'loadpoint': '25',
            'item_code': bom_lines[0][0].default_code,
            'process_face': 'single',
            'point_qty': 4,
        })
        return order, mo, rop, online

    def _flow(self, order, rop, online, lot, consumed_qty):
        self.env['sn.smt.material.consumption'].create({
            'serial_identity_id': self.identity.id,
            'mes_order_id': order.id,
            'route_operation_id': rop.id,
            'online_material_id': online.id,
            'material_lot_id': lot.id,
            'point_qty': 4,
            'consumed_qty': consumed_qty,
            'qty_before': consumed_qty,
            'qty_after': 0.0,
        })

    # ------------------------------------------------------------------
    # R3 scenarios
    # ------------------------------------------------------------------

    def test_full_substitution_no_double_deduct(self):
        """A 一颗未上机、全用 A1（有流水）、存在规则 → A1 按流水扣，
        A 的 BOM 行跳过兜底，完工成功不扣 A。"""
        comp_a = self._component('SBF-A')
        comp_a1 = self._component('SBF-A1')
        lot_a1 = self._lot(comp_a1, 'SBF-LOT-A1')
        order, mo, rop, online = self._order([(comp_a, 3.0)])
        self.rule_model.create({
            'original_product_id': comp_a.id,
            'substitute_product_id': comp_a1.id,
        })
        self._flow(order, rop, online, lot_a1, 6.0)
        order.x_output_qty = 10.0
        moves = order._mes_backflush(10.0)
        a1_moves = moves.filtered(lambda m: m.product_id == comp_a1)
        a_moves = moves.filtered(lambda m: m.product_id == comp_a)
        self.assertAlmostEqual(sum(a1_moves.mapped('product_uom_qty')), 6.0)
        self.assertFalse(a_moves, 'substituted BOM line must be skipped')

    def test_partial_substitution_flows_both(self):
        """A 用 3、A1 用 6（均有流水）→ 各按流水扣，A 行因有流水跳过兜底。"""
        comp_a = self._component('SBF-P-A')
        comp_a1 = self._component('SBF-P-A1')
        lot_a = self._lot(comp_a, 'SBF-LOT-PA')
        lot_a1 = self._lot(comp_a1, 'SBF-LOT-PA1')
        order, mo, rop, online = self._order([(comp_a, 3.0)])
        self.rule_model.create({
            'original_product_id': comp_a.id,
            'substitute_product_id': comp_a1.id,
        })
        self._flow(order, rop, online, lot_a, 3.0)
        self._flow(order, rop, online, lot_a1, 6.0)
        order.x_output_qty = 10.0
        moves = order._mes_backflush(10.0)
        self.assertAlmostEqual(sum(
            moves.filtered(lambda m: m.product_id == comp_a).mapped(
                'product_uom_qty')), 3.0)
        self.assertAlmostEqual(sum(
            moves.filtered(lambda m: m.product_id == comp_a1).mapped(
                'product_uom_qty')), 6.0)
        self.assertFalse(moves.filtered(
            lambda m: m.product_id == comp_a
            and 'BOM fallback' in (m.description_picking_manual or '')))

    def test_no_rule_maintains_fallback(self):
        """替代料有流水但无规则 → A 无流水仍按 BOM 兜底（现状行为）。"""
        comp_a = self._component('SBF-N-A')
        comp_a1 = self._component('SBF-N-A1')
        self._lot(comp_a, 'SBF-LOT-NA')
        lot_a1 = self._lot(comp_a1, 'SBF-LOT-NA1')
        order, mo, rop, online = self._order([(comp_a, 3.0)])
        self._flow(order, rop, online, lot_a1, 6.0)
        order.x_output_qty = 10.0
        moves = order._mes_backflush(10.0)
        fallback = moves.filtered(
            lambda m: m.product_id == comp_a
            and 'BOM fallback' in (m.description_picking_manual or ''))
        # BOM 行 3.0 × 完工比例 1.0（BOM 量即 10 板份额）
        self.assertAlmostEqual(sum(fallback.mapped('product_uom_qty')), 3.0)

    def test_scrap_coverage_uses_rule(self):
        """报废覆盖走规则：被替代行报废落在在机替代料的卷上，不报主料。"""
        comp_a = self._component('SBF-S-A')
        comp_a1 = self._component('SBF-S-A1')
        lot_a1 = self._lot(comp_a1, 'SBF-LOT-SA1')
        order, mo, rop, online = self._order([(comp_a, 3.0)])
        self.rule_model.create({
            'original_product_id': comp_a.id,
            'substitute_product_id': comp_a1.id,
        })
        self._flow(order, rop, online, lot_a1, 6.0)
        reason = self.env['sn.wsd.scrap.reason'].create({
            'name': 'SBF Scrap', 'code': 'SBFSCR'})
        order._mes_scrap_components(rop, 2.0, scrap_reason=reason)
        scraps = self.env['stock.scrap'].search([
            ('product_id', 'in', [comp_a.id, comp_a1.id])])
        self.assertFalse(scraps.filtered(lambda s: s.product_id == comp_a),
                         'substituted product itself is not scrapped')
        sub_scrap = scraps.filtered(lambda s: s.product_id == comp_a1)
        # BOM 3.0 / 10 板 × 报废 2 板 = 0.6，落在 A1 卷上
        self.assertAlmostEqual(sum(sub_scrap.mapped('scrap_qty')), 0.6)
        self.assertEqual(sub_scrap.mapped('lot_id'), lot_a1)

    def test_mo_backfill_coverage_uses_rule(self):
        """MO 流水回填：被替代的 BOM move 不再倒冲（picked 置否交由
        既有取消逻辑），替代料按流水补建 move。"""
        comp_a = self._component('SBF-M-A')
        comp_a1 = self._component('SBF-M-A1')
        lot_a1 = self._lot(comp_a1, 'SBF-LOT-MA1')
        order, mo, rop, online = self._order([(comp_a, 3.0)])
        self.rule_model.create({
            'original_product_id': comp_a.id,
            'substitute_product_id': comp_a1.id,
        })
        self._flow(order, rop, online, lot_a1, 6.0)
        mo.action_confirm()
        mo._smt_backfill_raw_moves()
        a_move = mo.move_raw_ids.filtered(lambda m: m.product_id == comp_a)
        a1_move = mo.move_raw_ids.filtered(lambda m: m.product_id == comp_a1)
        self.assertFalse(a_move.filtered('picked'),
                         'substituted BOM move must not be consumed')
        self.assertAlmostEqual(sum(a1_move.mapped('quantity')), 6.0)
