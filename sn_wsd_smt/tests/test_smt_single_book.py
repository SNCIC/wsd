from unittest.mock import patch

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSmtSingleBook(TransactionCase):
    """单账本改造：净值聚合、完工倒冲回填（含替代料）、上料/转机取数
    切 stock.quant 在手、耗尽拒载、转机回退。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wh = cls.env['stock.warehouse'].search([], limit=1)
        cls.stock_location = cls.wh.lot_stock_id
        cls.product_fg = cls.env['product.product'].create({
            'name': 'Single Book Finished Good',
            'default_code': 'SBK-TST-FG',
            'is_storable': True,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Single Book Material',
            'default_code': 'SBK-TST-A',
            'tracking': 'lot',
            'is_storable': True,
        })
        cls.product_sub = cls.env['product.product'].create({
            'name': 'Single Book Substitute',
            'default_code': 'SBK-TST-SUB',
            'tracking': 'lot',
            'is_storable': True,
        })
        cls.lot = cls.env['stock.lot'].create({
            'name': 'SBK-LOT-A',
            'product_id': cls.product.id,
            'company_id': cls.env.company.id,
        })
        cls.lot_sub = cls.env['stock.lot'].create({
            'name': 'SBK-LOT-SUB',
            'product_id': cls.product_sub.id,
            'company_id': cls.env.company.id,
        })
        cls.env['stock.quant'].create({
            'product_id': cls.product.id,
            'location_id': cls.stock_location.id,
            'lot_id': cls.lot.id,
            'quantity': 100.0,
        })
        cls.env['stock.quant'].create({
            'product_id': cls.product_sub.id,
            'location_id': cls.stock_location.id,
            'lot_id': cls.lot_sub.id,
            'quantity': 50.0,
        })
        cls.workcenter = cls.env['mrp.workcenter'].create({'name': 'SBK WC'})
        cls.workshop = cls.env['sn.mrp.workshop'].create({'name': 'SBK WS'})
        cls.production_line = cls.env['sn.mrp.production.line'].create({
            'name': 'SBK LINE',
            'workshop_id': cls.workshop.id,
            'company_id': cls.env.company.id,
        })
        cls.production = cls.env['mrp.production'].create({
            'product_id': cls.product_fg.id,
            'product_qty': 10,
        })
        cls.mes_order = cls._create_mes_order(cls.production, 10)
        cls.online_a = cls.env['sn.smt.online.material'].create({
            'mes_order_id': cls.mes_order.id,
            'model_code': 'SBKTST',
            'device_seq': 1,
            'table_no': 'T1',
            'loadpoint': '25',
            'item_code': 'SBK-TST-A',
            'process_face': 'single',
        })
        cls.operation = cls.env['sn.wsd.operation'].create({'name': 'SBK Operation'})
        # 路由每制令单唯一：整类共用一条路由与工序实例
        cls.route = cls.env['sn.wsd.mes.order.route'].create({
            'mes_order_id': cls.mes_order.id,
        })
        cls.route_operation = cls.env['sn.wsd.mes.order.route.operation'].create({
            'mes_route_id': cls.route.id,
            'operation_id': cls.operation.id,
        })

    @classmethod
    def _create_mes_order(cls, production, qty):
        # Route materialization requires a released process route; the single
        # book tests never touch routes, so skip the setup like cart tests do.
        MesOrder = cls.env['sn.wsd.mes.order']
        with patch.object(type(MesOrder), '_setup_route', lambda self: True):
            return MesOrder.create({
                'production_id': production.id,
                'production_line_id': cls.production_line.id,
                'date_plan': fields.Date.today(),
                'planned_qty': qty,
            })

    def _create_route_operation(self):
        return self.route_operation

    def _create_consumption(self, lot, online_line, qty, suffix):
        identity = self.env['sn.wsd.serial.identity'].create({
            'name': 'SBK-SN-%s' % suffix,
            'origin_type': 'manual',
        })
        return self.env['sn.smt.material.consumption'].create({
            'company_id': self.env.company.id,
            'serial_identity_id': identity.id,
            'mes_order_id': self.mes_order.id,
            'route_operation_id': self._create_route_operation().id,
            'online_material_id': online_line.id,
            'material_lot_id': lot.id,
            'point_qty': abs(qty),
            'product_qty': 1.0 if qty > 0 else -1.0,
            'consumed_qty': qty,
            'qty_before': 0.0,
            'qty_after': 0.0,
        })

    # ------------------------------------------------------------------
    # Net aggregation
    # ------------------------------------------------------------------

    def test_net_consumption_by_lot(self):
        self._create_consumption(self.lot, self.online_a, 3.0, '001')
        self._create_consumption(self.lot, self.online_a, -1.0, '002')
        self._create_consumption(self.lot_sub, self.online_a, 5.0, '003')
        net = self.env['sn.smt.material.consumption']._net_consumption_by_lot(self.production)
        self.assertEqual(net.get(self.lot), 2.0)
        self.assertEqual(net.get(self.lot_sub), 5.0)

    def test_net_consumption_ignores_reversed_out(self):
        self._create_consumption(self.lot, self.online_a, 2.0, '004')
        self._create_consumption(self.lot, self.online_a, -2.0, '005')
        net = self.env['sn.smt.material.consumption']._net_consumption_by_lot(self.production)
        self.assertNotIn(self.lot, net)

    # ------------------------------------------------------------------
    # Backfill on MO done
    # ------------------------------------------------------------------

    def _prepare_raw_move(self):
        move = self.env['stock.move'].create(
            self.production._get_move_raw_values(self.product, 10.0, self.product.uom_id))
        move._action_confirm(merge=False)
        return move

    def test_backfill_retargets_lot_and_quantity(self):
        move = self._prepare_raw_move()
        self._create_consumption(self.lot, self.online_a, 3.0, '010')
        self._create_consumption(self.lot, self.online_a, -1.0, '011')
        self.production._smt_backfill_raw_moves()
        self.assertTrue(move.picked)
        lines = move.move_line_ids
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines.lot_id, self.lot)
        self.assertEqual(lines.quantity, 2.0)
        # 实际过账：quant 扣的是记录在案的那卷
        move.with_context(skip_mo_check=True)._action_done(cancel_backorder=True)
        self.assertEqual(self.lot._smt_on_hand_qty(), 98.0)

    def test_backfill_creates_substitute_move(self):
        self._prepare_raw_move()
        self._create_consumption(self.lot_sub, self.online_a, 5.0, '012')
        self.production._smt_backfill_raw_moves()
        sub_move = self.production.move_raw_ids.filtered(
            lambda mv: mv.product_id == self.product_sub)
        self.assertEqual(len(sub_move), 1)
        self.assertTrue(sub_move.picked)
        self.assertEqual(sub_move.move_line_ids.lot_id, self.lot_sub)
        self.assertEqual(sub_move.move_line_ids.quantity, 5.0)
        sub_move.with_context(skip_mo_check=True)._action_done(cancel_backorder=True)
        self.assertEqual(self.lot_sub._smt_on_hand_qty(), 45.0)

    def test_backfill_is_idempotent_after_posting(self):
        # 复完工/恢复流程会再次进入回填：已过账产品不得二次扣减
        move = self._prepare_raw_move()
        self._create_consumption(self.lot, self.online_a, 2.0, '014')
        self.production._smt_backfill_raw_moves()
        move.with_context(skip_mo_check=True)._action_done(cancel_backorder=True)
        self.assertEqual(self.lot._smt_on_hand_qty(), 98.0)
        self.production._smt_backfill_raw_moves()
        extra_moves = self.production.move_raw_ids.filtered(
            lambda mv: mv.product_id == self.product and mv.state != 'done')
        self.assertFalse(extra_moves)
        self.assertEqual(self.lot._smt_on_hand_qty(), 98.0)

    def test_backfill_zeroes_duplicate_bom_lines(self):
        first = self._prepare_raw_move()
        second = self.env['stock.move'].create(
            self.production._get_move_raw_values(self.product, 4.0, self.product.uom_id))
        second._action_confirm(merge=False)
        self._create_consumption(self.lot, self.online_a, 2.0, '013')
        self.production._smt_backfill_raw_moves()
        self.assertTrue(first.picked)
        self.assertFalse(second.picked)

    # ------------------------------------------------------------------
    # Loading sources from on-hand quantity
    # ------------------------------------------------------------------

    def test_loading_takes_on_hand_quantity(self):
        service = self.env['sn.smt.loading.service']
        service.load_material(self.mes_order, self.workcenter, '1.T1', '25', 'SBK-LOT-A')
        self.assertEqual(self.online_a.loaded_material_lot_id, self.lot)
        self.assertEqual(self.online_a.loaded_qty, 100.0)

    def test_depleted_lot_rejected(self):
        empty_lot = self.env['stock.lot'].create({
            'name': 'SBK-LOT-EMPTY',
            'product_id': self.product.id,
            'company_id': self.env.company.id,
        })
        service = self.env['sn.smt.loading.service']
        with self.assertRaises(ValidationError):
            service.load_material(self.mes_order, self.workcenter, '1.T1', '25', 'SBK-LOT-EMPTY')

    def _create_target_order(self):
        """转机目标单挂在自己的制造单下（同单超排会被排程约束拦下）。"""
        production = self.env['mrp.production'].create({
            'product_id': self.product_fg.id,
            'product_qty': 10,
        })
        order = self._create_mes_order(production, 10)
        line = self.env['sn.smt.online.material'].create({
            'mes_order_id': order.id,
            'model_code': 'SBKTST',
            'device_seq': 1,
            'table_no': 'T1',
            'loadpoint': '25',
            'item_code': 'SBK-TST-A',
            'process_face': 'single',
        })
        return order, line

    def test_counter_scopes_to_current_reel(self):
        # UAT 发现的缺陷回归：换料后行余量不得被历史卷的流水污染
        service = self.env['sn.smt.loading.service']
        service.load_material(self.mes_order, self.workcenter, '1.T1', '25', 'SBK-LOT-A')
        self._create_consumption(self.lot, self.online_a, 40.0, '030')
        self.assertEqual(self.online_a.remaining_qty, 60.0)
        lot_b = self.env['stock.lot'].create({
            'name': 'SBK-LOT-B',
            'product_id': self.product.id,
            'company_id': self.env.company.id,
        })
        self.env['stock.quant'].create({
            'product_id': self.product.id,
            'location_id': self.stock_location.id,
            'lot_id': lot_b.id,
            'quantity': 80.0,
        })
        service.change_material(self.mes_order, self.workcenter, '1.T1', '25', 'SBK-LOT-B')
        # 换卷后余量=新卷量，历史 40 点不计入
        self.assertEqual(self.online_a.remaining_qty, 80.0)
        self._create_consumption(lot_b, self.online_a, 30.0, '031')
        self.assertEqual(self.online_a.remaining_qty, 50.0)

    def test_mes_flow_net_by_lot_hook(self):
        # 制令单完工倒冲的取数钩子：按单过滤、净值口径
        self._create_consumption(self.lot, self.online_a, 5.0, '040')
        self._create_consumption(self.lot, self.online_a, -2.0, '041')
        net = self.mes_order._mes_flow_net_by_lot()
        self.assertEqual(net.get(self.lot), 3.0)

    def test_changeover_fallback_while_source_open(self):
        service = self.env['sn.smt.loading.service']
        service.load_material(self.mes_order, self.workcenter, '1.T1', '25', 'SBK-LOT-A')
        # 源单行剩余 60：在手 100，已耗 40（倒冲未入账，在手虚高）
        self._create_consumption(self.lot, self.online_a, 40.0, '020')
        self.assertEqual(self.online_a.remaining_qty, 60.0)
        target_order, target_line = self._create_target_order()
        service.changeover(self.mes_order, target_order, self.workcenter)
        # 未完工回退：取旧单行剩余而不是虚高的在手
        self.assertEqual(target_line.loaded_qty, 60.0)

    def test_changeover_uses_quant_when_source_done(self):
        service = self.env['sn.smt.loading.service']
        service.load_material(self.mes_order, self.workcenter, '1.T1', '25', 'SBK-LOT-A')
        self.production.state = 'done'
        target_order, target_line = self._create_target_order()
        service.changeover(self.mes_order, target_order, self.workcenter)
        self.assertEqual(target_line.loaded_qty, 100.0)
