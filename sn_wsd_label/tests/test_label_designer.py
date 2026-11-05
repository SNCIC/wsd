from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLabelDesignerHelpers(TransactionCase):
    """Paper preset write-through and designer-friendly duplication."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template_model = cls.env['sn.label.template']
        cls.partner_model_id = cls.env['ir.model']._get_id('res.partner')

    def _create_template(self, **kwargs):
        values = {
            'name': 'Preset Template',
            'model_id': self.partner_model_id,
            'element_ids': [Command.create({
                'element_type': 'text', 'content': 'fixed',
                'fixed_text': 'Tooling Code', 'x': 10, 'y': 10,
                'width': 120, 'height': 30,
            })],
        }
        values.update(kwargs)
        return self.template_model.create(values)

    def test_paper_preset_matches_known_sizes(self):
        template = self._create_template(width_dots=560, height_dots=320)
        self.assertEqual(template.paper_preset, '70x40')
        template.width_dots = 480
        template.height_dots = 320
        self.assertEqual(template.paper_preset, '60x40')
        template.width_dots = 123
        self.assertEqual(template.paper_preset, 'custom')

    def test_paper_preset_writes_dimensions(self):
        template = self._create_template(width_dots=560, height_dots=320)
        template.paper_preset = '88x88'
        self.assertEqual((template.width_dots, template.height_dots), (709, 709))

    def test_duplicate_template_copies_elements(self):
        template = self._create_template(name='Original')
        action = template.action_duplicate_template()
        copy = self.template_model.browse(action['res_id'])
        self.assertNotEqual(copy, template)
        self.assertIn('(copy)', copy.name)
        self.assertEqual(len(copy.element_ids), len(template.element_ids))
        self.assertEqual(copy.element_ids[0].fixed_text, 'Tooling Code')
