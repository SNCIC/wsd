from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDrawingMaterial(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        def _get_or_create(model, code_key, code, name, **kw):
            existing = cls.env[model].search([(code_key, '=', code)], limit=1)
            return existing or cls.env[model].create({code_key: code, 'name': name, **kw})

        cls.workshop = _get_or_create('sn.mrp.workshop', 'name', 'DM TEST WS', 'DM TEST WS')
        cls.operation = _get_or_create(
            'sn.wsd.operation', 'name', 'DM Test Operation', 'DM Test Operation')
        cls.tooling_type = _get_or_create(
            'sn.tooling.type', 'name', 'DM Test Tooling Type', 'DM Test Tooling Type')
        cls.tooling_template = _get_or_create(
            'sn.tooling.template', 'code', 'DM-TL-01', 'DM Test Stencil',
            type_id=cls.tooling_type.id, spec='120x80')
        cls.tooling_template2 = _get_or_create(
            'sn.tooling.template', 'code', 'DM-TL-02', 'DM Test Carrier',
            type_id=cls.tooling_type.id)
        cls.consumable_type = _get_or_create(
            'sn.consumable.type', 'name', 'DM Test Consumable Type', 'DM Test Consumable Type')
        cls.consumable_template = _get_or_create(
            'sn.consumable.template', 'code', 'DM-CONS-01', 'DM Test Solder Paste',
            type_id=cls.consumable_type.id, spec='500g',
            shelf_life_days=180, expiry_remind_days=30)
        cls.material_product = cls.env['product.product'].create({
            'name': 'DM Test Chip',
            'default_code': 'DM-MAT-01',
        })
        cls.drawing_product = cls.env['product.product'].create({
            'name': 'DM Test Board',
            'default_code': 'DM-DWG-01',
        })

    def _create_relation(self, **kw):
        values = {
            'workshop_id': self.workshop.id,
            'x_drawing_no': 'DM-DWG-01',
            'operation_id': self.operation.id,
            'x_side': 'top',
        }
        values.update(kw)
        return self.env['sn.wsd.drawing.material'].create(values)

    def _ref(self, record):
        return '{},{}'.format(record._name, record.id)

    def test_unique_dimension(self):
        self._create_relation()
        with self.assertRaises(IntegrityError):
            self._create_relation()

    def test_sides_coexist(self):
        top = self._create_relation(x_side='top')
        bottom = self._create_relation(x_side='bottom')
        self.assertTrue(top and bottom)

    def test_workshop_dimension_coexist(self):
        other_workshop = self.env['sn.mrp.workshop'].create({'name': 'DM TEST WS 2'})
        first = self._create_relation()
        second = self._create_relation(workshop_id=other_workshop.id)
        self.assertTrue(first and second)

    def test_product_info_derived(self):
        relation = self._create_relation()
        self.assertEqual(relation.product_id, self.drawing_product)
        self.assertEqual(relation.product_name, 'DM Test Board')

        unknown = self._create_relation(x_drawing_no='DM-DWG-UNKNOWN')
        self.assertFalse(unknown.product_id)
        self.assertFalse(unknown.product_name)

    def test_display_name(self):
        relation = self._create_relation()
        self.assertIn('DM-DWG-01', relation.display_name)
        self.assertIn('DM Test Operation', relation.display_name)
        self.assertIn('Top', relation.display_name)

    def test_material_type_derived(self):
        relation = self._create_relation()
        lines = self.env['sn.wsd.drawing.material.line'].create([
            {
                'drawing_material_id': relation.id,
                'material_ref': self._ref(self.tooling_template),
            },
            {
                'drawing_material_id': relation.id,
                'material_ref': self._ref(self.consumable_template),
            },
            {
                'drawing_material_id': relation.id,
                'material_ref': self._ref(self.material_product),
            },
        ])
        self.assertEqual(lines.mapped('material_type'), ['tooling', 'consumable', 'material'])

    def test_line_duplicate_rejected(self):
        relation = self._create_relation()
        line_model = self.env['sn.wsd.drawing.material.line']
        line_model.create({
            'drawing_material_id': relation.id,
            'material_ref': self._ref(self.consumable_template),
            'qty': 1,
        })
        with self.assertRaises(IntegrityError):
            line_model.create({
                'drawing_material_id': relation.id,
                'material_ref': self._ref(self.consumable_template),
                'qty': 2,
            })

    def test_multiple_lines_same_type_allowed(self):
        relation = self._create_relation()
        line_model = self.env['sn.wsd.drawing.material.line']
        lines = line_model.create([
            {
                'drawing_material_id': relation.id,
                'material_ref': self._ref(self.tooling_template),
            },
            {
                'drawing_material_id': relation.id,
                'material_ref': self._ref(self.tooling_template2),
            },
        ])
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines.mapped('material_type'), ['tooling', 'tooling'])

    def test_line_defaults_and_sequence(self):
        relation = self._create_relation()
        line_model = self.env['sn.wsd.drawing.material.line']
        first = line_model.create({
            'drawing_material_id': relation.id,
            'material_ref': self._ref(self.tooling_template),
        })
        second = line_model.create({
            'drawing_material_id': relation.id,
            'material_ref': self._ref(self.material_product),
        })
        self.assertEqual(first.qty, 1.0)
        self.assertEqual(first.usage_times, 1)
        self.assertEqual(first.sequence, 10)
        self.assertEqual(second.sequence, 20)
        self.assertEqual(relation.line_ids, first + second)

    def test_line_material_info(self):
        relation = self._create_relation()
        lines = self.env['sn.wsd.drawing.material.line'].create([
            {
                'drawing_material_id': relation.id,
                'material_ref': self._ref(self.tooling_template),
            },
            {
                'drawing_material_id': relation.id,
                'material_ref': self._ref(self.consumable_template),
            },
            {
                'drawing_material_id': relation.id,
                'material_ref': self._ref(self.material_product),
            },
        ])
        tooling_line, consumable_line, material_line = lines
        self.assertEqual(tooling_line.material_name, 'DM Test Stencil')
        self.assertEqual(tooling_line.material_spec, '120x80')
        self.assertEqual(consumable_line.material_name, 'DM Test Solder Paste')
        self.assertEqual(consumable_line.material_spec, '500g')
        self.assertEqual(material_line.material_name, 'DM Test Chip')

    def test_line_qty_usage_validation(self):
        relation = self._create_relation()
        line_model = self.env['sn.wsd.drawing.material.line']
        with self.assertRaises(ValidationError):
            line_model.create({
                'drawing_material_id': relation.id,
                'material_ref': self._ref(self.tooling_template),
                'qty': 0,
            })
        with self.assertRaises(ValidationError):
            line_model.create({
                'drawing_material_id': relation.id,
                'material_ref': self._ref(self.tooling_template),
                'usage_times': 0,
            })
