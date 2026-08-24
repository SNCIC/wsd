import psycopg2
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSnSmtCart(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product_a = cls.env['product.product'].create({
            'name': 'Cart Test Material A',
            'default_code': 'CART-TST-A',
        })
        cls.product_sub = cls.env['product.product'].create({
            'name': 'Cart Test Material Substitute',
            'default_code': 'CART-TST-SUB',
        })
        cls.product_a.substitute_ids = [Command.link(cls.product_sub.id)]
        cls.product_b = cls.env['product.product'].create({
            'name': 'Cart Test Material B',
            'default_code': 'CART-TST-B',
        })
        cls.lot_a = cls.env['stock.lot'].create({
            'name': 'CART-LOT-A',
            'product_id': cls.product_a.id,
            'company_id': cls.env.company.id,
        })
        cls.lot_sub = cls.env['stock.lot'].create({
            'name': 'CART-LOT-SUB',
            'product_id': cls.product_sub.id,
            'company_id': cls.env.company.id,
        })
        cls.lot_b = cls.env['stock.lot'].create({
            'name': 'CART-LOT-B',
            'product_id': cls.product_b.id,
            'company_id': cls.env.company.id,
        })
        cls.workcenter = cls.env['mrp.workcenter'].create({'name': 'CART WC'})
        cls.workshop = cls.env['sn.mrp.workshop'].create({'name': 'CART TEST WS'})
        cls.production_line = cls.env['sn.mrp.production.line'].create({
            'name': 'CART TEST LINE',
            'workshop_id': cls.workshop.id,
            'company_id': cls.env.company.id,
        })
        cls.production = cls.env['mrp.production'].create({
            'product_id': cls.product_a.id,
            'product_qty': 10,
        })
        cls.mes_order = cls._create_mes_order(cls.production, 10)
        cls.online_a = cls.env['sn.smt.online.material'].create({
            'mes_order_id': cls.mes_order.id,
            'model_code': 'CARTTST',
            'device_seq': 1,
            'table_no': '1',
            'loadpoint': '25',
            'item_code': 'CART-TST-A',
            'process_face': 'single',
        })
        cls.online_b = cls.env['sn.smt.online.material'].create({
            'mes_order_id': cls.mes_order.id,
            'model_code': 'CARTTST',
            'device_seq': 1,
            'table_no': '1',
            'loadpoint': '30',
            'item_code': 'CART-TST-B',
            'process_face': 'single',
        })
        cls.cart = cls.env['sn.smt.cart'].create({'cart_sn': 'CART-TST-001'})
        cls.cart2 = cls.env['sn.smt.cart'].create({'cart_sn': 'CART-TST-002'})

    @classmethod
    def _create_mes_order(cls, production, qty):
        # Route materialization requires a released process route bound to the
        # drawing number; cart logic never touches routes, so skip it here.
        MesOrder = cls.env['sn.wsd.mes.order']
        with patch.object(type(MesOrder), '_setup_route', lambda self: True):
            return MesOrder.create({
                'production_id': production.id,
                'production_line_id': cls.production_line.id,
                'date_plan': fields.Date.today(),
                'planned_qty': qty,
            })

    def _create_feeder(self, sn):
        return self.env['sn.smt.feeder'].create({
            'feeder_sn': sn,
            'channel_type': 'single',
            'channel_ids': [Command.create({'channel_no': 1, 'channel_sn': sn})],
        })

    def _bind(self, cart, feeder, slot, lot, mes_order=None):
        return self.env['sn.smt.cart.line'].create({
            'cart_id': cart.id,
            'feeder_id': feeder.id,
            'slot_no': slot,
            'material_lot_id': lot.id,
            'mes_order_id': (mes_order or self.mes_order).id,
        })

    # ------------------------------------------------------------------
    # Master data
    # ------------------------------------------------------------------

    def test_cart_sn_unique(self):
        with self.assertRaises(psycopg2.IntegrityError):
            with self.env.cr.savepoint():
                self.env['sn.smt.cart'].create({'cart_sn': 'CART-TST-001'})

    def test_cart_name_is_cart_sn(self):
        self.assertEqual(self.cart.name, 'CART-TST-001')

    # ------------------------------------------------------------------
    # Line validation
    # ------------------------------------------------------------------

    def test_bind_sets_loaded_and_feeder_cart(self):
        feeder = self._create_feeder('CART-FDR-001')
        line = self._bind(self.cart, feeder, '25', self.lot_a)
        self.assertFalse(line.removed_at)
        self.assertEqual(self.cart.status, 'loaded')
        self.assertEqual(feeder.cart_id, self.cart)

    def test_bind_rejects_wrong_material(self):
        feeder = self._create_feeder('CART-FDR-002')
        with self.assertRaises(UserError):
            self._bind(self.cart, feeder, '25', self.lot_b)

    def test_bind_allows_substitute_material(self):
        feeder = self._create_feeder('CART-FDR-003')
        line = self._bind(self.cart, feeder, '25', self.lot_sub)
        self.assertEqual(line.material_lot_id, self.lot_sub)

    def test_bind_rejects_unknown_station(self):
        feeder = self._create_feeder('CART-FDR-004')
        with self.assertRaises(UserError):
            self._bind(self.cart, feeder, '99', self.lot_a)

    def test_bind_rejects_second_mes_order(self):
        feeder = self._create_feeder('CART-FDR-005')
        self._bind(self.cart, feeder, '25', self.lot_a)
        other_feeder = self._create_feeder('CART-FDR-006')
        production2 = self.env['mrp.production'].create({
            'product_id': self.product_a.id,
            'product_qty': 5,
        })
        mes_order2 = self._create_mes_order(production2, 5)
        with self.assertRaises(UserError):
            self._bind(self.cart, other_feeder, '30', self.lot_b, mes_order=mes_order2)

    def test_bind_rejects_feeder_on_other_cart(self):
        feeder = self._create_feeder('CART-FDR-007')
        self._bind(self.cart, feeder, '25', self.lot_a)
        with self.assertRaises(UserError):
            self._bind(self.cart2, feeder, '30', self.lot_b)

    def test_bind_rejects_occupied_station(self):
        feeder = self._create_feeder('CART-FDR-008')
        self._bind(self.cart, feeder, '25', self.lot_a)
        feeder2 = self._create_feeder('CART-FDR-009')
        with self.assertRaises(UserError):
            self._bind(self.cart, feeder2, '25', self.lot_a)

    def test_bind_rejects_duplicate_lot(self):
        feeder = self._create_feeder('CART-FDR-010')
        self._bind(self.cart, feeder, '25', self.lot_a)
        feeder2 = self._create_feeder('CART-FDR-011')
        with self.assertRaises(UserError):
            self._bind(self.cart2, feeder2, '30', self.lot_a)

    # ------------------------------------------------------------------
    # Mount / unmount
    # ------------------------------------------------------------------

    def test_mount_unmount_kit_cache(self):
        feeder = self._create_feeder('CART-FDR-012')
        self._bind(self.cart, feeder, '25', self.lot_a)
        self.cart.action_mount(self.workcenter)
        self.assertEqual(self.cart.status, 'mounted')
        self.assertEqual(self.cart.mounted_workcenter_id, self.workcenter)
        self.assertTrue(self.cart.mounted_at)
        self.cart.action_unmount()
        self.assertEqual(self.cart.status, 'loaded')
        self.assertFalse(self.cart.mounted_workcenter_id)
        self.assertTrue(self.cart.unmounted_at)
        self.assertTrue(self.cart._get_active_lines())

    def test_mount_blocks_wrong_material(self):
        feeder = self._create_feeder('CART-FDR-013')
        self._bind(self.cart, feeder, '25', self.lot_a)
        # the MES order requirement changes after the cart was prepared
        self.online_a.item_code = 'CART-TST-B'
        with self.assertRaises(UserError):
            self.cart.action_mount(self.workcenter)

    def test_mount_allows_missing_station(self):
        feeder = self._create_feeder('CART-FDR-014')
        # only station 25 prepared, station 30 missing: shared-material changeover
        self._bind(self.cart, feeder, '25', self.lot_a)
        self.cart.action_mount(self.workcenter)
        self.assertEqual(self.cart.status, 'mounted')

    def test_mount_rejects_twice(self):
        feeder = self._create_feeder('CART-FDR-015')
        self._bind(self.cart, feeder, '25', self.lot_a)
        self.cart.action_mount(self.workcenter)
        with self.assertRaises(UserError):
            self.cart.action_mount(self.workcenter)
        self.assertEqual(self.cart.status, 'mounted')

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def test_disable_requires_unmounted(self):
        feeder = self._create_feeder('CART-FDR-016')
        self._bind(self.cart, feeder, '25', self.lot_a)
        self.cart.action_mount(self.workcenter)
        with self.assertRaises(UserError):
            self.cart.action_disable()
        self.cart.action_unmount()
        self.cart.action_disable()
        self.assertEqual(self.cart.status, 'disabled')
        self.cart.action_enable()
        self.assertEqual(self.cart.status, 'loaded')

    def test_scrap_requires_empty_cart(self):
        feeder = self._create_feeder('CART-FDR-017')
        self._bind(self.cart, feeder, '25', self.lot_a)
        with self.assertRaises(UserError):
            self.cart.action_scrap()
        self.cart.action_clear_lines()
        self.assertEqual(self.cart.status, 'idle')
        self.cart.action_scrap()
        self.assertEqual(self.cart.status, 'scrapped')

    def test_unbind_restores_idle(self):
        feeder = self._create_feeder('CART-FDR-018')
        line = self._bind(self.cart, feeder, '25', self.lot_a)
        line.action_unbind()
        self.assertTrue(line.removed_at)
        self.assertFalse(feeder.cart_id)
        self.assertEqual(self.cart.status, 'idle')
        # feeder is free again and can be rebound on another cart
        self._bind(self.cart2, feeder, '30', self.lot_b)

    # ------------------------------------------------------------------
    # Feeder guards
    # ------------------------------------------------------------------

    def test_feeder_scrap_blocked_while_on_cart(self):
        feeder = self._create_feeder('CART-FDR-019')
        self._bind(self.cart, feeder, '25', self.lot_a)
        with self.assertRaises(UserError):
            feeder.action_scrap(reason='test')
        self.cart.action_clear_lines()
        feeder.action_scrap(reason='test')
        self.assertEqual(feeder.status, 'scrapped')
