import base64

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLabelTemplate(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template_model = cls.env['sn.label.template']
        cls.partner_model_id = cls.env['ir.model']._get_id('res.partner')
        cls.designer_group = cls.env.ref('sn_wsd_label.group_designer')
        cls.partner = cls.env['res.partner'].create({
            'name': '钢网 GW-0001',
            'street': 'Line 2',
            'company_id': cls.env.company.id,
        })

    def _create_template(self, elements=None, **kwargs):
        values = {
            'name': 'Stencil Label',
            'model_id': self.partner_model_id,
            'width_dots': 560,
            'height_dots': 320,
            'sn_field': 'name',
        }
        values.update(kwargs)
        if elements is not None:
            values['element_ids'] = elements
        return self.template_model.create(values)

    def test_layout_dict_serialization(self):
        template = self._create_template(elements=[
            Command.create({'sequence': 30, 'element_type': 'qrcode',
                            'content': 'field', 'field_path': 'name',
                            'x': 400, 'y': 100, 'width': 120, 'height': 120}),
            Command.create({'sequence': 10, 'element_type': 'box',
                            'x': 8, 'y': 8, 'width': 544, 'height': 304,
                            'thickness': 2}),
            Command.create({'sequence': 20, 'element_type': 'text',
                            'content': 'fixed', 'fixed_text': '工具码',
                            'x': 20, 'y': 20, 'width': 100, 'height': 30,
                            'font_size': 24, 'max_lines': 1, 'align': 'left'}),
        ])
        layout = template._to_layout_dict()
        self.assertEqual(layout['width'], 560)
        self.assertEqual(layout['height'], 320)
        self.assertEqual([element['type'] for element in layout['elements']],
                         ['box', 'text', 'qrcode'])
        text_element = layout['elements'][1]
        self.assertEqual(text_element['text'], '工具码')
        self.assertEqual(text_element['font_size'], 24)
        qr_element = layout['elements'][2]
        self.assertEqual(qr_element['field_path'], 'name')
        self.assertEqual(qr_element['rendering'], 'native')

    def test_template_renders_all_dialects(self):
        template = self._create_template(elements=[
            Command.create({'element_type': 'text', 'content': 'fixed',
                            'fixed_text': '工具码', 'x': 20, 'y': 20,
                            'width': 150, 'height': 30, 'font_size': 24}),
            Command.create({'element_type': 'text', 'content': 'field',
                            'field_path': 'name', 'x': 20, 'y': 60,
                            'width': 240, 'height': 30, 'font_size': 26}),
            Command.create({'element_type': 'qrcode', 'content': 'field',
                            'field_path': 'name', 'x': 400, 'y': 100,
                            'width': 120, 'height': 120}),
        ])
        renderer = self.env['sn.label.renderer']
        layout = template._to_layout_dict()
        zpl = renderer.render_zpl(layout, self.partner)
        self.assertIn('^XA', zpl)
        self.assertIn('工具码' and '^GFA,', zpl)
        cpcl = renderer.render_cpcl_json(layout, self.partner)
        self.assertIn('BITMAP', [command['tag'] for command in cpcl])
        png = renderer.render_png(layout, self.partner)
        self.assertTrue(png.startswith(b'\x89PNG'))

    def test_constraint_fixed_requires_text(self):
        with self.assertRaises(ValidationError):
            self._create_template(elements=[
                Command.create({'element_type': 'text', 'content': 'fixed',
                                'fixed_text': False, 'x': 20, 'y': 20,
                                'width': 100, 'height': 30}),
            ])

    def test_constraint_field_requires_valid_path(self):
        with self.assertRaises(ValidationError):
            self._create_template(elements=[
                Command.create({'element_type': 'qrcode', 'content': 'field',
                                'field_path': 'message_ids', 'x': 20,
                                'y': 20, 'width': 100, 'height': 100}),
            ])
        with self.assertRaises(ValidationError):
            self._create_template(elements=[
                Command.create({'element_type': 'text', 'content': 'field',
                                'field_path': False, 'x': 20, 'y': 20,
                                'width': 100, 'height': 30}),
            ])

    def test_constraint_geometry(self):
        with self.assertRaises(ValidationError):
            self._create_template(elements=[
                Command.create({'element_type': 'text', 'content': 'fixed',
                                'fixed_text': 'X', 'x': -1, 'y': 20,
                                'width': 100, 'height': 30}),
            ])
        with self.assertRaises(ValidationError):
            self._create_template(width_dots=0)

    def test_designer_permissions(self):
        template = self._create_template()
        demo = self.env.ref('base.user_demo')
        # internal user without the designer group: read-only
        self.assertEqual(template.with_user(demo).name, 'Stencil Label')
        with self.assertRaises(AccessError):
            template.with_user(demo).write({'name': 'Nope'})
        # designer can edit
        demo.group_ids = [Command.link(self.designer_group.id)]
        template.with_user(demo).write({'name': 'Renamed'})
        self.assertEqual(template.name, 'Renamed')

    def test_company_isolation(self):
        company2 = self.env['res.company'].create({'name': 'Second Site'})
        user2 = self.env['res.users'].create({
            'name': 'Label User 2',
            'login': 'label_user_2',
            'email': 'label_user_2@example.com',
            'company_id': company2.id,
            'company_ids': [Command.link(company2.id)],
            'group_ids': [Command.link(self.env.ref('base.group_user').id)],
        })
        template_global = self._create_template(
            name='Global Label', company_id=False)
        template_private = self._create_template(
            name='Private Label', company_id=self.env.company.id)
        visible = self.template_model.with_user(user2).search([])
        self.assertIn(template_global, visible)
        self.assertNotIn(template_private, visible)

    def test_preview_uses_selected_record(self):
        other = self.env['res.partner'].create({'name': '最新记录'})
        template = self._create_template(elements=[
            Command.create({'element_type': 'text', 'content': 'field',
                            'field_path': 'name', 'x': 20, 'y': 20,
                            'width': 300, 'height': 30, 'font_size': 26}),
        ])
        # no explicit record: most recent record wins
        self.assertEqual(template._preview_record(), other)
        # explicit record wins over most recent
        template.preview_res_id = self.partner.id
        self.assertEqual(template._preview_record(), self.partner)
        png_bytes = template._preview_png_bytes()
        self.assertTrue(png_bytes.startswith(b'\x89PNG'))
        decoded = base64.b64decode(template.preview_image)
        self.assertTrue(decoded.startswith(b'\x89PNG'))

    def test_placeholder_png(self):
        template = self._create_template()
        self.assertTrue(
            template._placeholder_png('No record available for preview.')
            .startswith(b'\x89PNG'))

    def test_field_path_options(self):
        reader = self.env['sn.label.reader']
        options = dict(reader.field_path_options('res.partner'))
        self.assertIn('name', options)
        self.assertIn('company_id.name', options)
        self.assertIn('/', options['company_id.name'])
        picker_options = self.env['sn.label.element'].with_context(
            label_model='res.partner')._selection_field_paths()
        self.assertIn(('name', options['name']), picker_options)
