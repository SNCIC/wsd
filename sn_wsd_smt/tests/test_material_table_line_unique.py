"""Material table line exclusivity: per company + model code + product side,
a production line may be linked to at most one valid (is_valid='Y') table.

- different lines across same-model tables: allowed
- same line on two valid tables of same model/side: rejected with the
  conflicting table named in the error
- different sides (double-sided board T/B): allowed
- invalidating a table releases its lines; re-validating against a taken
  line is rejected again
- editing the header (model code) onto a taken combination is rejected too
"""

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMaterialTableLineUnique(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.workshop = cls.env['sn.mrp.workshop'].create(
            {'name': 'WS-MTU', 'code': 'WSMTU'})
        Line = cls.env['sn.mrp.production.line']
        cls.line_1 = Line.create(
            {'name': 'MTU-L1', 'code': 'MTU-L1', 'workshop_id': cls.workshop.id})
        cls.line_2 = Line.create(
            {'name': 'MTU-L2', 'code': 'MTU-L2', 'workshop_id': cls.workshop.id})
        cls.table_model = cls.env['sn.smt.material.table']

    def _create_table(self, model_code, side, lines, **extra):
        return self.table_model.create({
            'table_name': extra.pop('table_name', 'TBL-%s-%s' % (model_code, side)),
            'model_code': model_code,
            'product_side': side,
            'line_link_ids': [(0, 0, {'production_line_id': line.id}) for line in lines],
            **extra,
        })

    def test_different_lines_allowed(self):
        table_a = self._create_table('W2335', 'top', self.line_1, table_name='TBL-A')
        table_b = self._create_table('W2335', 'top', self.line_2, table_name='TBL-B')
        self.assertEqual(table_a.line_link_ids.production_line_id, self.line_1)
        self.assertEqual(table_b.line_link_ids.production_line_id, self.line_2)

    def test_same_line_rejected_with_conflict_named(self):
        self._create_table('W2335', 'top', self.line_1, table_name='TBL-A')
        with self.assertRaises(ValidationError) as ctx:
            self._create_table('W2335', 'top', self.line_1, table_name='TBL-B')
        message = str(ctx.exception)
        self.assertIn('MTU-L1', message)
        self.assertIn('TBL-A', message)

    def test_different_side_allowed(self):
        self._create_table('W2335', 'top', self.line_1, table_name='TBL-T')
        # double-sided board: T and B tables may share the same line
        self._create_table('W2335', 'bottom', self.line_1, table_name='TBL-B')

    def test_invalid_table_releases_line(self):
        table_a = self._create_table('W2335', 'top', self.line_1, table_name='TBL-A')
        table_a.is_valid = 'N'
        self._create_table('W2335', 'top', self.line_1, table_name='TBL-B')
        # re-validating the old table while the new one holds the line: rejected
        with self.assertRaises(ValidationError):
            table_a.is_valid = 'Y'

    def test_header_model_code_change_rejected(self):
        self._create_table('W2335', 'top', self.line_1, table_name='TBL-A')
        table_x = self._create_table('W2336', 'top', self.line_1, table_name='TBL-X')
        with self.assertRaises(ValidationError):
            table_x.model_code = 'W2335'
