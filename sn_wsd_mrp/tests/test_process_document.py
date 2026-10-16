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
        cls.mo_target = cls.env['mrp.production'].create({
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

    def _quick_entry(self, lines):
        wizard = self.env['production.process.doc.quick.entry.wizard'].create({
            'production_id': self.mo.id,
            'line_ids': [(0, 0, line) for line in lines],
        })
        return wizard, wizard.action_apply()

    def test_quick_entry_merges_same_combo_into_one_list(self):
        software_type = self.env.ref('sn_wsd_mrp.doc_type_production_software')
        _, action = self._quick_entry([
            {'operation_id': self.op_smt.id, 'type_id': self.doc_type.id,
             'codes_text': 'PLAN-A, PLAN-B'},
            # same operation + type on a second line: merged, deduped
            {'operation_id': self.op_smt.id, 'type_id': self.doc_type.id,
             'codes_text': 'PLAN-B\nPLAN-C'},
            {'operation_id': self.op_smt.id, 'type_id': software_type.id,
             'codes_text': 'SW-001'},
        ])
        docs = self.env['production.process.document'].search([
            ('production_id', '=', self.mo.id)])
        self.assertEqual(len(docs), 2)
        param_doc = docs.filtered(lambda d: d.type_id == self.doc_type)
        self.assertEqual(
            sorted(param_doc.code_ids.mapped('code')),
            ['PLAN-A', 'PLAN-B', 'PLAN-C'])
        self.assertEqual(action['tag'], 'display_notification')

    def test_quick_entry_appends_to_existing_list(self):
        doc = self._create_doc(route_operation_code='SMTPRG')
        doc.code_ids = [(0, 0, {'code': 'PLAN-A'})]
        _, action = self._quick_entry([{
            'operation_id': self.op_smt.id, 'type_id': self.doc_type.id,
            'codes_text': 'PLAN-A, PLAN-B',
        }])
        docs = self.env['production.process.document'].search([
            ('production_id', '=', self.mo.id),
            ('type_id', '=', self.doc_type.id)])
        self.assertEqual(len(docs), 1)
        self.assertEqual(
            sorted(docs.code_ids.mapped('code')), ['PLAN-A', 'PLAN-B'])
        message = action['params']['message']
        self.assertIn('1', message)

    def _copy_wizard(self, source, target, docs):
        wizard = self.env['production.process.doc.copy.wizard'].create({
            'source_production_id': source.id,
            'target_production_id': target.id,
            'line_ids': [(0, 0, {'source_document_id': doc.id}) for doc in docs],
        })
        return wizard.action_apply()

    def test_copy_creates_lists_on_target_order(self):
        doc_a = self._create_doc(
            route_operation_code='SMTPRG', operation_id=self.op_smt.id)
        doc_a.code_ids = [(0, 0, {'code': 'PLAN-A'}),
                          (0, 0, {'code': 'PLAN-B'})]
        action = self._copy_wizard(self.mo, self.mo_target, doc_a)
        copied = self.env['production.process.document'].search([
            ('production_id', '=', self.mo_target.id)])
        self.assertEqual(len(copied), 1)
        self.assertEqual(copied.operation_id, self.op_smt)
        self.assertEqual(copied.type_id, self.doc_type)
        self.assertEqual(
            sorted(copied.code_ids.mapped('code')), ['PLAN-A', 'PLAN-B'])
        self.assertEqual(action['tag'], 'display_notification')

    def test_copy_appends_to_existing_target_list(self):
        doc_a = self._create_doc(
            route_operation_code='SMTPRG', operation_id=self.op_smt.id)
        doc_a.code_ids = [(0, 0, {'code': 'PLAN-A'}),
                          (0, 0, {'code': 'PLAN-B'})]
        # 目标单已有同组合清单，带一个交集编号
        target_doc = self.env['production.process.document'].create({
            'production_id': self.mo_target.id,
            'operation_id': self.op_smt.id,
            'route_operation_code': 'SMTPRG',
            'type_id': self.doc_type.id,
            'code_ids': [(0, 0, {'code': 'PLAN-A'})],
        })
        self._copy_wizard(self.mo, self.mo_target, doc_a)
        self.assertEqual(
            sorted(target_doc.code_ids.mapped('code')), ['PLAN-A', 'PLAN-B'])
        docs = self.env['production.process.document'].search([
            ('production_id', '=', self.mo_target.id)])
        self.assertEqual(len(docs), 1)
