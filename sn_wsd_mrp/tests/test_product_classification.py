from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductClassification(TransactionCase):
    """The classification rule guards the template creation.

    A variant creation builds its template first while ``default_code`` stays
    on the variant: the template never carries the code, so the rule must not
    reject ``product.product.create`` (the programmatic API used by the MES
    flows and the test fixtures) and the native defaults apply instead.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category = cls.env.ref('product.product_category_goods')

    def test_template_requires_a_category(self):
        with self.assertRaises(ValidationError):
            self.env['product.template'].create({
                'name': 'Unclassified Product',
                'default_code': 'ZZ-NO-CATEGORY',
            })

    def test_template_requires_a_material_code(self):
        with self.assertRaises(ValidationError):
            self.env['product.template'].create({
                'name': 'Uncoded Product',
                'categ_id': self.category.id,
            })

    def test_template_with_category_and_code_is_accepted(self):
        template = self.env['product.template'].create({
            'name': 'Classified Product',
            'default_code': 'ZZ-CLASSIFIED',
            'categ_id': self.category.id,
        })
        self.assertEqual(template.product_variant_id.default_code, 'ZZ-CLASSIFIED')

    def test_variant_creation_carries_its_material_code(self):
        product = self.env['product.product'].create({
            'name': 'Variant With Code',
            'default_code': 'ZZ-VARIANT-001',
            'categ_id': self.category.id,
            'is_storable': True,
        })
        self.assertEqual(product.default_code, 'ZZ-VARIANT-001')
        self.assertEqual(product.product_tmpl_id.default_code, 'ZZ-VARIANT-001')
        self.assertEqual(product.categ_id, self.category)

    def test_variant_creation_keeps_the_native_defaults(self):
        """A component created by a flow without a code stays valid: the
        programmatic API keeps the native behaviour, the rule guards the
        product form."""
        product = self.env['product.product'].create({
            'name': 'Variant Without Code',
            'is_storable': True,
        })
        self.assertFalse(product.default_code)
