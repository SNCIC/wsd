from unittest.mock import patch

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMaterialOperationDeduction(TransactionCase):
    """料站表扣点按物料关联工序（x_material_operation_id）接线：
    只在该工序出站扣、他站不扣不拦、未维护且有料站表行硬拦、幂等维持。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wh = cls.env['stock.warehouse'].search([], limit=1)
        cls.stock_location = cls.wh.lot_stock_id
        cls.product_fg = cls.env['product.product'].create({
            'name': 'MOD Finished Good',
            'default_code': 'MOD-TST-FG',
            'is_storable': True,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'MOD Material',
            'default_code': 'MOD-TST-A',
            'tracking': 'lot',
            'is_storable': True,
        })
        cls.lot = cls.env['stock.lot'].create({
            'name': 'MOD-LOT-A',
            'product_id': cls.product.id,
            'company_id': cls.env.company.id,
        })
        cls.env['stock.quant'].create({
            'product_id': cls.product.id,
            'location_id': cls.stock_location.id,
            'lot_id': cls.lot.id,
            'quantity': 100.0,
        })
        cls.workcenter = cls.env['mrp.workcenter'].create({'name': 'MOD WC'})
        cls.workshop = cls.env['sn.mrp.workshop'].create({'name': 'MOD WS'})
        cls.production_line = cls.env['sn.mrp.production.line'].create({
            'name': 'MOD LINE',
            'workshop_id': cls.workshop.id,
            'company_id': cls.env.company.id,
        })
        # SMT 工艺路线：印刷 → 贴片，物料关联工序 = 贴片
        cls.op_print = cls.env['sn.wsd.operation'].create({'name': 'MOD Print'})
        cls.op_place = cls.env['sn.wsd.operation'].create({'name': 'MOD Placement'})
        cls.process_route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
            'name': 'MOD SMT Route',
            'code': 'MOD-SMT-RT',
            'x_process_type': 'smt',
            'x_workshop_id': cls.workshop.id,
        })
        cls.mes_order = cls._create_mes_order(10)
        cls.online_a = cls.env['sn.smt.online.material'].create({
            'mes_order_id': cls.mes_order.id,
            'model_code': 'MODTST',
            'device_seq': 1,
            'table_no': 'T1',
            'loadpoint': '25',
            'item_code': 'MOD-TST-A',
            'process_face': 'single',
            'point_qty': 4,
        })
        cls.private_route = cls.env['sn.wsd.mes.order.route'].create({
            'mes_order_id': cls.mes_order.id,
            'route_id': cls.process_route.id,
        })
        cls.mes_order.x_mes_route_id = cls.private_route.id
        cls.rop_print = cls.env['sn.wsd.mes.order.route.operation'].create({
            'mes_route_id': cls.private_route.id,
            'operation_id': cls.op_print.id,
            'sequence': 10,
        })
        cls.rop_place = cls.env['sn.wsd.mes.order.route.operation'].create({
            'mes_route_id': cls.private_route.id,
            'operation_id': cls.op_place.id,
            'sequence': 20,
        })
        cls.private_route.x_material_operation_id = cls.rop_place.id
        cls.env['sn.smt.loading.service'].load_material(
            cls.mes_order, cls.workcenter, '1.T1', '25', cls.lot.name)
        cls.identity = cls.env['sn.wsd.serial.identity'].create({
            'name': 'MOD-SN-001',
            'origin_type': 'manual',
        })

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

    def _consume(self, route_operation, **kwargs):
        return self.env['sn.smt.material.consumption'].consume_for_serial(
            route_operation, identity=self.identity, **kwargs)

    def test_deduct_at_material_operation(self):
        created = self._consume(self.rop_place)
        self.assertEqual(len(created), 1)
        self.assertEqual(created.route_operation_id, self.rop_place)
        self.assertEqual(created.online_material_id, self.online_a)
        self.assertEqual(self.online_a.remaining_qty, 96.0)

    def test_no_deduct_nor_block_at_other_operation(self):
        created = self._consume(self.rop_print)
        self.assertFalse(created)
        self.assertFalse(self.env['sn.smt.material.consumption'].search([
            ('mes_order_id', '=', self.mes_order.id),
        ]))
        self.assertEqual(self.online_a.remaining_qty, 100.0)

    def test_unmaintained_material_operation_blocks(self):
        self.private_route.x_material_operation_id = False
        with self.assertRaises(ValidationError):
            self._consume(self.rop_place)

    def test_material_operation_outside_route_blocks(self):
        other = self._create_mes_order(5)
        other_route = self.env['sn.wsd.mes.order.route'].create({
            'mes_order_id': other.id,
        })
        other.x_mes_route_id = other_route.id
        other_rop = self.env['sn.wsd.mes.order.route.operation'].create({
            'mes_route_id': other_route.id,
            'operation_id': self.op_print.id,
        })
        # 把别单的工序实例维护成本单的物料关联工序：归属非法，按未维护拦截
        self.private_route.x_material_operation_id = other_rop.id
        with self.assertRaises(ValidationError):
            self._consume(self.rop_place)

    def test_no_table_rows_no_block(self):
        other = self._create_mes_order(5)
        other_route = self.env['sn.wsd.mes.order.route'].create({
            'mes_order_id': other.id,
            'route_id': self.process_route.id,
        })
        other.x_mes_route_id = other_route.id
        other_rop = self.env['sn.wsd.mes.order.route.operation'].create({
            'mes_route_id': other_route.id,
            'operation_id': self.op_place.id,
        })
        created = self.env['sn.smt.material.consumption'].consume_for_serial(
            other_rop, identity=self.identity)
        self.assertFalse(created)

    def test_same_order_deducted_once_across_stations(self):
        first = self._consume(self.rop_place)
        # 贴片 NG 重过后再 OK：按单幂等，不重复扣
        again = self._consume(self.rop_place)
        self.assertEqual(again, first)
        self.assertEqual(self.online_a.remaining_qty, 96.0)

    def test_external_event_id_idempotent(self):
        first = self._consume(self.rop_place, external_event_id='MOD-EVT-1')
        again = self._consume(self.rop_place, external_event_id='MOD-EVT-1')
        self.assertEqual(again, first)
        self.assertEqual(len(first), 1)
