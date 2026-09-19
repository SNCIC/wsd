from odoo.addons.stock_account.tests.common import TestStockValuationCommon
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestStockQuantValueReadGroup(TestStockValuationCommon):
    """分组报表会用 web_read_group 取 value:sum / value:sum_currency，
    批量聚合的结果必须与逐条 _compute_value 的结果一致。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.shelf_location = cls.env['stock.location'].create({
            'name': 'Quant Value Shelf',
            'location_id': cls.stock_location.id,
            'usage': 'internal',
        })
        cls.product_a = cls.env['product.product'].create({
            **cls.product_common_vals,
            'name': 'Quant Value A',
            'categ_id': cls.category_standard_auto.id,
            'standard_price': 12.5,
        })
        cls.product_b = cls.env['product.product'].create({
            **cls.product_common_vals,
            'name': 'Quant Value B',
            'categ_id': cls.category_standard_auto.id,
            'standard_price': 4.0,
        })
        cls.product_lot = cls.env['product.product'].create({
            **cls.product_common_vals,
            'name': 'Quant Value Lot',
            'categ_id': cls.category_avco.id,
            'standard_price': 7.0,
            'tracking': 'lot',
            'lot_valuated': True,
        })
        cls.lot = cls.env['stock.lot'].create({
            'name': 'QUANT-VALUE-LOT-1',
            'product_id': cls.product_lot.id,
        })
        # _make_in_move 是实例方法，setUpClass 里把 cls 当 self 传入即可
        cls._make_in_move(cls, cls.product_a, 10, 12.5)
        # 同一产品放在两个库位，验证分组汇总会把组内多条 quant 相加
        cls._make_in_move(cls, cls.product_a, 3, 12.5, location_dest_id=cls.shelf_location.id)
        cls._make_in_move(cls, cls.product_b, 5, 4.0)
        cls._make_in_move(cls, cls.product_lot, 2, 7.0, lot_ids=[cls.lot])
        cls.products = cls.product_a + cls.product_b + cls.product_lot

    def _assert_aggregate_matches_values(self, aggregate):
        domain = [('product_id', 'in', self.products.ids)]
        rows = self.env['stock.quant']._read_group(domain, ['product_id'], [aggregate])
        self.assertEqual(len(rows), len(self.products))
        total = 0.0
        for product, value in rows:
            quants = self.env['stock.quant'].search([('product_id', '=', product.id)])
            quants.invalidate_recordset(['value'])
            total += value
            self.assertAlmostEqual(value, sum(quants.mapped('value')), places=2)
        self.assertNotEqual(total, 0.0, "测试数据必须有非零价值，否则比较没有意义")

    def test_value_sum(self):
        self._assert_aggregate_matches_values('value:sum')

    def test_value_sum_currency(self):
        self._assert_aggregate_matches_values('value:sum_currency')
