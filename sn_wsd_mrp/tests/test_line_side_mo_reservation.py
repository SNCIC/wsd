from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLineSideMoReservation(TransactionCase):
    """line-side-mo-reservation（在制有主、完工无主）：

    - 领料（WH/MI）/补料（WH/OP）验证后，MO 组件需求从线边做原生预留
      （记名到 MO 级；主库自由量永不锁给 MO）；
    - 跨 MO：他单领料预留跳过本单已占的卷；同 MO 兄弟制令单共享；
    - 倒冲/报废按消耗量减留；退料生成时解留（退料单自身随即占用）；
    - MO 完工 _on_done cancel 组件 move → 原生自动解留，剩卷回流共享池；
    - 完工硬校验口径 = 自由量 + 本 MO 预留（校验与 BOM 兜底分配同源）。
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create({
            'name': 'WS-LMSR', 'code': 'WSLSR'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'LSR', 'code': 'LSR', 'workshop_id': cls.workshop.id})
        cls.bom_workshop = cls.env['sn.mrp.workshop'].create({
            'name': 'WS-LMSR-BOM', 'code': 'WSLSRB'})
        cls.wh = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1)
        if cls.wh and cls.wh.manufacture_steps != 'mrp_one_step' and cls.wh.pbm_loc_id:
            cls.bom_workshop.component_location_id = cls.env['stock.location'].create({
                'name': 'LMSR-BOM-COMP', 'usage': 'internal',
                'location_id': cls.wh.pbm_loc_id.id,
            }).id
        if cls.wh and cls.wh.manufacture_steps == 'pbm_sam' and cls.wh.sam_loc_id:
            cls.bom_workshop.finished_product_location_id = cls.env['stock.location'].create({
                'name': 'LMSR-BOM-FP', 'usage': 'internal',
                'location_id': cls.wh.sam_loc_id.id,
            }).id
        # 线边挂在主库位之下（真实部署形态）：他单领料的 child_of 全院
        # 找料能看见线边，跨 MO 保护才有意义
        cls.line_side = cls.env['stock.location'].create({
            'name': 'LMSR-LINE-SIDE', 'usage': 'internal',
            'location_id': cls.wh.lot_stock_id.id,
        })
        cls.workshop.component_location_id = cls.line_side.id
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True,
        ).create({
            'name': 'RT-LSR', 'code': 'RTLSR', 'x_workshop_id': cls.workshop.id,
        })
        Operation = cls.env['sn.wsd.operation']
        cls.op_in = Operation.create(
            {'name': 'LSR-IN', 'code': 'LSRIN', 'x_station_type': 'assembly'})
        cls.op_out = Operation.create(
            {'name': 'LSR-OUT', 'code': 'LSROUT', 'x_station_type': 'final_test'})
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
            'route_id': cls.route.id, 'x_drawing_no': 'DWG-LSR',
        })
        cls.component = cls.env['product.product'].create({
            'name': 'COMP-LSR', 'uom_id': cls.uom_unit.id, 'is_storable': True,
        })
        cls.lot_component = cls.env['product.product'].create({
            'name': 'COMP-LOT-LSR', 'uom_id': cls.uom_unit.id,
            'is_storable': True, 'tracking': 'lot',
        })

    def _make_mo(self, qty=10, component=None):
        """MO：BOM 一行组件 2/台，BOM 车间独立（多步仓库防源=目的）。"""
        component = component or self.component
        product = self.env['product.product'].create({
            'name': 'P-LSR', 'uom_id': self.uom_unit.id,
            'default_code': 'DWG-LSR', 'x_board_side': 'single',
        })
        bom = self.env['mrp.bom'].create({
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
        return self.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': qty,
            'bom_id': bom.id, 'company_id': self.company.id,
        })

    def _make_order(self, mo, qty, manage_mode='station'):
        return self.env['sn.wsd.mes.order'].create({
            'production_id': mo.id,
            'production_line_id': self.line.id,
            'date_plan': fields.Date.today(),
            'planned_qty': qty,
            'x_manage_mode': manage_mode,
        })

    def _stock_main(self, product, qty, lot=False):
        vals = {
            'product_id': product.id,
            'location_id': self.wh.lot_stock_id.id,
            'quantity': qty,
        }
        if lot:
            vals['lot_id'] = lot.id
        return self.env['stock.quant'].create(vals)

    def _deliver(self, order, qty_this=None):
        """生成并验证一张领料单（主库→线边），触发 MO 级建留。"""
        order.action_generate_picking(qty_this=qty_this)
        picking = order.picking_ids.filtered(lambda p: p.state != 'cancel')[-1]
        picking.move_ids.picked = True
        picking.button_validate()
        self.assertEqual(picking.state, 'done')
        return picking

    def _quant(self, location, product, lot=False):
        domain = [('product_id', '=', product.id),
                  ('location_id', '=', location.id)]
        if lot:
            domain.append(('lot_id', '=', lot.id))
        return self.env['stock.quant'].search(domain)

    def _mo_reserved(self, order, product, lot=False):
        if lot:
            return order._mes_own_line_side_reserved(product, lot)
        return sum(order._mes_mo_line_side_move_lines().filtered(
            lambda ml: ml.product_id == product).mapped(
                'quantity_product_uom'))

    # --- A1/建留：领料验证把落线边的料占给 MO；主库不锁（A7） ---
    def test_01_issue_validation_reserves_to_mo(self):
        mo = self._make_mo()
        order = self._make_order(mo, 4)
        self._stock_main(self.component, 100)
        self._deliver(order)
        # MO 组件 move：需求 20（2/台×10），线边预留 8（4 台份额）
        raw = mo.move_raw_ids.filtered(
            lambda m: m.product_id == self.component)
        self.assertAlmostEqual(self._mo_reserved(order, self.component), 8.0)
        self.assertIn(raw.state, ('assigned', 'partially_available'))
        self.assertTrue(all(
            ml.location_id == self.line_side
            for ml in raw.move_line_ids.filtered(lambda l: not l.picked)),
            'MO reservation lines must live at the line side only')
        quant = self._quant(self.line_side, self.component)
        self.assertAlmostEqual(quant.quantity, 8.0)
        self.assertAlmostEqual(quant.reserved_quantity, 8.0)
        # A7: 主库自由量不被 MO 锁定（领料单自身的预留已随验证消失）
        main = self._quant(self.wh.lot_stock_id, self.component)
        self.assertAlmostEqual(main.reserved_quantity, 0.0)

    # --- A1: 他 MO 领料跳过本单已占的卷，改从主库取 ---
    def test_02_cross_mo_picking_skips_reserved(self):
        mo_a = self._make_mo()
        order_a = self._make_order(mo_a, 4)
        self._stock_main(self.component, 100)
        self._deliver(order_a)
        mo_b = self._make_mo()
        order_b = self._make_order(mo_b, 4)
        picking_b = self._deliver(order_b)
        # B 的领料预留全部来自主库：线边 8 已被 A 的 MO 占住
        self.assertFalse(any(
            ml.location_id == self.line_side
            for ml in picking_b.move_ids.move_line_ids),
            'MO B must not reserve MO A line-side stock')
        self.assertAlmostEqual(
            self._mo_reserved(order_a, self.component), 8.0,
            msg='MO A reservation untouched by MO B picking')
        quant = self._quant(self.line_side, self.component)
        # B 的领料验证后，B 自己送达的 8 也占给 B 的 MO（各占各的）
        self.assertAlmostEqual(quant.reserved_quantity, 16.0)

    # --- A2/A4: 同 MO 兄弟制令单共享；完工硬校验计自由量+本单预留 ---
    def test_03_sibling_share_and_completion_counts_own(self):
        mo = self._make_mo()
        order_1 = self._make_order(mo, 4)
        order_2 = self._make_order(mo, 4)
        self._stock_main(self.component, 100)
        self._deliver(order_1)  # 8 pcs 落线边，占给 MO
        quant = self._quant(self.line_side, self.component)
        self.assertAlmostEqual(quant.reserved_quantity, 8.0)
        # 兄弟制令单完工倒冲 4 台 = 8 pcs：自由量 0 + 本 MO 预留 8 → 放行
        moves = order_2._mes_backflush(4)
        self.assertAlmostEqual(sum(
            m.quantity for m in moves
            if m.product_id == self.component), 8.0)
        quant = self._quant(self.line_side, self.component)
        self.assertAlmostEqual(quant.quantity, 0.0)
        self.assertAlmostEqual(quant.reserved_quantity, 0.0,
                                msg='backflush must release the reservation')

    # --- A4 反例: 他 MO 的预留不算进本单完工可用量 ---
    def test_04_completion_blocked_by_other_mo_reservation(self):
        mo_a = self._make_mo()
        order_a = self._make_order(mo_a, 4)
        self._stock_main(self.component, 100)
        self._deliver(order_a)  # 8 pcs 全部占给 MO A
        mo_b = self._make_mo()
        order_b = self._make_order(mo_b, 4)
        self._deliver(order_b)  # 又 8 pcs 占给 MO B
        # B 完工倒冲 8 台 = 16 pcs > 自由 0 + 本 MO 预留 8 → 硬拦
        with self.assertRaises(ValidationError) as ctx:
            order_b._mes_backflush(8)
        self.assertIn('insufficient', str(ctx.exception))

    # --- A5a/A3: 倒冲减留；MO 完工 cancel 自动解留、剩卷回流共享池 ---
    def test_05_backflush_then_mo_done_releases_leftovers(self):
        mo = self._make_mo()
        order = self._make_order(mo, 4)
        self._stock_main(self.component, 100)
        self._deliver(order)  # 8 pcs 占给 MO
        order._mes_backflush(2)  # 消耗 4 pcs，同步减留
        quant = self._quant(self.line_side, self.component)
        self.assertAlmostEqual(quant.quantity, 4.0)
        self.assertAlmostEqual(quant.reserved_quantity, 4.0)
        # 全部制令单完工 → _on_done cancel 组件 move → 原生自动解留
        order.state = 'done'
        order._on_done()
        self.assertEqual(mo.state, 'done')
        quant = self._quant(self.line_side, self.component)
        self.assertAlmostEqual(quant.quantity, 4.0)
        self.assertAlmostEqual(quant.reserved_quantity, 0.0,
                                msg='MO closure must free the leftover coil')
        # 剩卷回流共享池：新 MO 的建留（只在 child_of 线边找料）可直接
        # 占用回流的自由量——B 单验证后自身送达 8 + 回流 4 全部占给 B
        mo_b = self._make_mo()
        order_b = self._make_order(mo_b, 4)
        self._deliver(order_b)
        self.assertAlmostEqual(
            self._mo_reserved(order_b, self.component), 12.0,
            msg='the released leftover must be claimable by a new order')

    # --- A5b: 报废扣线边后按量减留 ---
    def test_06_scrap_releases_reservation(self):
        mo = self._make_mo()
        order = self._make_order(mo, 4, manage_mode='report')
        self._stock_main(self.component, 100)
        self._deliver(order)
        self.assertAlmostEqual(self._mo_reserved(order, self.component), 8.0)
        reason = self.env['sn.wsd.scrap.reason'].search([], limit=1)
        self.assertTrue(reason, 'scrap reason fixture data is required')
        op = order.x_route_operation_ids.filtered(
            lambda r: r.operation_id == self.op_in)[:1]
        order.report_operation_qty(op, 2, qty_scrap=1, scrap_reason=reason)
        # 报废 1 板 × 2 pcs：线边数量与预留同步减少
        quant = self._quant(self.line_side, self.component)
        self.assertAlmostEqual(quant.quantity, 6.0)
        self.assertAlmostEqual(quant.reserved_quantity, 6.0)

    # --- A6: 退料解留（优先退本单占用的卷），验证后量随货回主库 ---
    def test_07_return_releases_reservation(self):
        mo = self._make_mo(component=self.lot_component)
        order = self._make_order(mo, 4)
        lot_a = self.env['stock.lot'].create({
            'product_id': self.lot_component.id, 'name': 'LSR-LOT-A',
            'company_id': self.company.id,
        })
        lot_b = self.env['stock.lot'].create({
            'product_id': self.lot_component.id, 'name': 'LSR-LOT-B',
            'company_id': self.company.id,
        })
        self._stock_main(self.lot_component, 4, lot=lot_a)
        self._stock_main(self.lot_component, 4, lot=lot_b)
        self._deliver(order)  # 两卷各 4 pcs 落线边并占给 MO
        self.assertAlmostEqual(
            self._mo_reserved(order, self.lot_component), 8.0)
        order.action_generate_return(qty=2)  # 4 pcs：整卷优先退本单占用的卷
        return_picking = order.picking_ids.filtered(
            lambda p: p.picking_type_id
            == self.wh.picking_type_return_id)
        self.assertTrue(return_picking)
        lines = return_picking.move_line_ids.filtered(
            lambda l: l.location_id == self.line_side)
        self.assertAlmostEqual(sum(l.quantity for l in lines), 4.0)
        # 解留 4：MO 预留降到 4，退料单自身占用 4，账面不超预留
        self.assertAlmostEqual(
            self._mo_reserved(order, self.lot_component), 4.0)
        lots_quants = self.env['stock.quant'].search([
            ('product_id', '=', self.lot_component.id),
            ('location_id', '=', self.line_side.id)])
        self.assertAlmostEqual(sum(lots_quants.mapped('quantity')), 8.0)
        self.assertAlmostEqual(sum(lots_quants.mapped('reserved_quantity')), 8.0)
        # 验证退料单：料回主库，线边量与预留同步走账
        return_picking.move_ids.picked = True
        return_picking.button_validate()
        self.assertEqual(return_picking.state, 'done')
        lots_quants = self.env['stock.quant'].search([
            ('product_id', '=', self.lot_component.id),
            ('location_id', '=', self.line_side.id)])
        self.assertAlmostEqual(sum(lots_quants.mapped('quantity')), 4.0)
        self.assertAlmostEqual(sum(lots_quants.mapped('reserved_quantity')), 4.0)

    # --- 补料（WH/OP）验证同样建立 MO 级预留 ---
    def test_08_supplement_picking_participates(self):
        mo = self._make_mo()
        order = self._make_order(mo, 4)
        self._stock_main(self.component, 100)
        self._deliver(order)
        self.assertAlmostEqual(self._mo_reserved(order, self.component), 8.0)
        order.action_generate_over_picking(
            [{'product_id': self.component.id, 'qty': 3.0}],
            reason='supplement for test')
        supplement = order.picking_ids.filtered(
            lambda p: p.picking_type_id
            == self.wh.picking_type_over_pick_id)
        self.assertTrue(supplement)
        supplement.move_ids.picked = True
        supplement.button_validate()
        self.assertEqual(supplement.state, 'done')
        self.assertAlmostEqual(
            self._mo_reserved(order, self.component), 11.0,
            msg='the supplement must be reserved to the MO as well')
