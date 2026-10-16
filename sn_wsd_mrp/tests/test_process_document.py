"""Process documents: the operation picker drives the stored operation
code (the device-API match key), while the MO + operation + type
uniqueness keeps guarding duplicates."""

from odoo.tests import TransactionCase, tagged
from psycopg2 import IntegrityError


@tagged('post_install', '-at_install')
class TestProcessDocument(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env['product.product'].create({
            'name': 'P-PROCESS-DOC',
            'is_storable': True,
        })
        cls.mo = cls.env['mrp.production'].create({
            'product_id': cls.product.id,
            'product_qty': 1,
        })
        cls.doc_type = cls.env.ref('sn_wsd_mrp.doc_type_parameter_plan')
        Operation = cls.env['sn.wsd.operation']
        cls.op_smt = Operation.create({
            'name': 'SMT Program', 'code': 'SMTPRG',
            'x_station_type': 'assembly',
        })
        cls.op_no_code = Operation.create({
            'name': 'Final Check', 'x_station_type': 'final_test',
        })
        # code 有序列默认值；无 code 是遗留路径，清空后验证 name 兜底
        cls.op_no_code.code = False

    def _create_doc(self, **values):
        return self.env['production.process.document'].create({
            'production_id': self.mo.id,
            'type_id': self.doc_type.id,
            **values,
        })

    def test_operation_picker_syncs_code(self):
        doc = self.env['production.process.document'].new({
            'production_id': self.mo.id,
        })
        doc.operation_id = self.op_smt
        doc._onchange_operation_id()
        self.assertEqual(doc.route_operation_code, 'SMTPRG')

    def test_operation_picker_falls_back_to_name(self):
        doc = self.env['production.process.document'].new({
            'production_id': self.mo.id,
        })
        doc.operation_id = self.op_no_code
        doc._onchange_operation_id()
        self.assertEqual(doc.route_operation_code, 'Final Check')

    def test_same_operation_type_blocked_per_mo(self):
        self._create_doc(route_operation_code='SMTPRG')
        with self.assertRaises(IntegrityError):
            self._create_doc(route_operation_code='SMTPRG')

    def test_different_operations_share_type(self):
        self._create_doc(route_operation_code='SMTPRG')
        # one order, several lists of the same type on different operations
        self._create_doc(route_operation_code='APIIN2')
