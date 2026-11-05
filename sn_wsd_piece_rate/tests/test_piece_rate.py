from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPieceRate(TransactionCase):
    """piece-rate 批次1：单价主数据——公司+产品+工序唯一、单价必须为正。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env['product.product'].create({
            'name': 'PR-METER',
            'default_code': 'PR-METER',
        })
        cls.operation = cls.env['sn.wsd.operation'].create({
            'name': 'PR Assembly',
        })

    def _create_rate(self, price=0.3):
        return self.env['sn.wsd.piece.rate'].create({
            'product_id': self.product.id,
            'operation_id': self.operation.id,
            'price': price,
        })

    def test_duplicate_company_product_operation_rejected(self):
        self._create_rate()
        with self.assertRaises(IntegrityError):
            self._create_rate(price=0.35)

    def test_price_must_be_positive(self):
        with self.assertRaises(ValidationError):
            self._create_rate(price=0.0)
