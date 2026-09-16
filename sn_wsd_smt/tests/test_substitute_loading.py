from unittest.mock import patch

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSubstituteLoading(TransactionCase):
    """substitute-rule R2：上料放行走规则——全局/单级命中放行、未命中拒绝
    且提示列出可用替代料、换料自动判定、转机继承。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wh = cls.env['stock.warehouse'].search([], limit=1)
        cls.stock_location = cls.wh.lot_stock_id
        cls.product_fg = cls.env['product.product'].create({
            'name': 'SUB-LD FG', 'default_code': 'SUB-LD-FG',
            'is_storable': True,
        })
        cls.product_a = cls._material(cls, 'SUB-LD-A')
        cls.product_a1 = cls._material(cls, 'SUB-LD-A1')
        cls.product_b = cls._material(cls, 'SUB-LD-B')
        cls.lot_a = cls._lot(cls, cls.product_a, 'SUB-LOT-A')
        cls.lot_a1 = cls._lot(cls, cls.product_a1, 'SUB-LOT-A1')
        cls.lot_b = cls._lot(cls, cls.product_b, 'SUB-LOT-B')
        cls.workcenter = cls.env['mrp.workcenter'].create({'name': 'SUB-LD WC'})
        cls.workshop = cls.env['sn.mrp.workshop'].create({'name': 'SUB-LD WS'})
        cls.production_line = cls.env['sn.mrp.production.line'].create({
            'name': 'SUB-LD LINE',
            'workshop_id': cls.workshop.id,
            'company_id': cls.env.company.id,
        })
        cls.mes_order = cls._create_mes_order(10)
        cls.other_order = cls._create_mes_order(10)
        cls.env['sn.smt.online.material'].create({
            'mes_order_id': cls.mes_order.id,
            'model_code': 'SUB-LD-FG',
            'device_seq': 1,
            'table_no': 'T1',
            'loadpoint': '25',
            'item_code': 'SUB-LD-A',
            'process_face': 'single',
            'point_qty': 4,
        })
        cls.env['sn.smt.online.material'].create({
            'mes_order_id': cls.other_order.id,
            'model_code': 'SUB-LD-FG',
            'device_seq': 1,
            'table_no': 'T1',
            'loadpoint': '25',
            'item_code': 'SUB-LD-A',
            'process_face': 'single',
            'point_qty': 4,
        })
        cls.service = cls.env['sn.smt.loading.service']

    def _material(cls, code):
        return cls.env['product.product'].create({
            'name': code, 'default_code': code,
            'tracking': 'lot', 'is_storable': True,
        })

    def _lot(cls, product, name):
        lot = cls.env['stock.lot'].create({
            'name': name, 'product_id': product.id,
            'company_id': cls.env.company.id,
        })
        cls.env['stock.quant'].create({
            'product_id': product.id,
            'location_id': cls.stock_location.id,
            'lot_id': lot.id,
            'quantity': 100.0,
        })
        return lot

    @classmethod
    def _create_mes_order(cls, qty):
        MesOrder = cls.env['sn.wsd.mes.order']
        production = cls.env['mrp.production'].create({
            'product_id': cls.product_fg.id,
            'product_qty': qty,
        })
        with patch.object(type(MesOrder), '_setup_route', lambda self: True):
            return MesOrder.create({
                'production_id': production.id,
                'production_line_id': cls.production_line.id,
                'date_plan': fields.Date.today(),
                'planned_qty': qty,
            })

    def _online_row(self, order):
        return order.x_smt_online_material_ids.filtered(
            lambda line: line.loadpoint == '25')[:1]

    # ------------------------------------------------------------------
    # R2 scenarios
    # ------------------------------------------------------------------

    def test_global_rule_allows_substitute_load(self):
        self.env['sn.wsd.substitute.rule'].create({
            'original_product_id': self.product_a.id,
            'substitute_product_id': self.product_a1.id,
        })
        self.service.load_material(
            self.mes_order, self.workcenter, '1.T1', '25', self.lot_a1.name)
        row = self._online_row(self.mes_order)
        self.assertEqual(row.is_load, 'Y')
        self.assertEqual(row.loaded_material_lot_id, self.lot_a1)
        log = self.env['sn.smt.material.log'].search([
            ('online_material_id', '=', row.id),
            ('operation_type', '=', 'online_load'),
        ], limit=1)
        self.assertEqual(log.required_item_code, 'SUB-LD-A')
        self.assertEqual(log.material_lot_id, self.lot_a1)

    def test_scoped_rule_hits_own_order_only(self):
        self.env['sn.wsd.substitute.rule'].create({
            'original_product_id': self.product_a.id,
            'substitute_product_id': self.product_a1.id,
            'scope': 'orders',
            'mes_order_ids': [(6, 0, [self.mes_order.id])],
        })
        # 命中本单
        self.service.load_material(
            self.mes_order, self.workcenter, '1.T1', '25', self.lot_a1.name)
        self.assertEqual(self._online_row(self.mes_order).is_load, 'Y')
        # 不命中他单（规则只对 mes_order 生效）
        with self.assertRaises(ValidationError):
            self.service.load_material(
                self.other_order, self.workcenter, '1.T1', '25', 'SUB-LOT-A1')

    def test_rejection_lists_substitutes(self):
        self.env['sn.wsd.substitute.rule'].create({
            'original_product_id': self.product_a.id,
            'substitute_product_id': self.product_a1.id,
        })
        with self.assertRaises(ValidationError) as ctx:
            self.service.load_material(
                self.mes_order, self.workcenter, '1.T1', '25', self.lot_b.name)
        self.assertIn('SUB-LD-A, SUB-LD-A1', str(ctx.exception))

    def test_rejection_without_rule_lists_requirement_only(self):
        with self.assertRaises(ValidationError) as ctx:
            self.service.load_material(
                self.mes_order, self.workcenter, '1.T1', '25', self.lot_b.name)
        self.assertIn('SUB-LD-A', str(ctx.exception))
        self.assertNotIn('SUB-LD-A1', str(ctx.exception))

    def test_change_to_substitute_records_change(self):
        self.env['sn.wsd.substitute.rule'].create({
            'original_product_id': self.product_a.id,
            'substitute_product_id': self.product_a1.id,
        })
        self.service.load_material(
            self.mes_order, self.workcenter, '1.T1', '25', self.lot_a.name)
        result = self.service.change_material(
            self.mes_order, self.workcenter, '1.T1', '25', self.lot_a1.name)
        row = self._online_row(self.mes_order)
        self.assertEqual(row.loaded_material_lot_id, self.lot_a1)
        self.assertEqual(row.replace_count, 1)
        self.assertEqual(result['old_material_lot_id'], self.lot_a.id)
        log = self.env['sn.smt.material.log'].search([
            ('online_material_id', '=', row.id),
            ('operation_type', '=', 'change'),
        ], limit=1)
        self.assertTrue(log)

    def test_changeover_inherits_substitute(self):
        self.env['sn.wsd.substitute.rule'].create({
            'original_product_id': self.product_a.id,
            'substitute_product_id': self.product_a1.id,
        })
        self.service.load_material(
            self.mes_order, self.workcenter, '1.T1', '25', self.lot_a1.name)
        result = self.service.changeover(
            self.mes_order, self.other_order, self.workcenter)
        self.assertIn('25', result['inherited_slots'])
        self.assertNotIn('25', result['manual_slots'])
        row = self._online_row(self.other_order)
        self.assertEqual(row.is_load, 'Y')
        self.assertEqual(row.loaded_material_lot_id, self.lot_a1)

    def test_product_level_relation_not_honored(self):
        """R4：仅产品级 substitute_ids（无规则）不再放行。"""
        self.product_a.substitute_ids = [(6, 0, [self.product_a1.id])]
        with self.assertRaises(ValidationError):
            self.service.load_material(
                self.mes_order, self.workcenter, '1.T1', '25', 'SUB-LOT-A1')
