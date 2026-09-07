import io

from PIL import Image

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLabelLinks(TransactionCase):
    """Connector batch: seed templates and print entry points shipped by
    sn_wsd_label_links (label-center design decision 8)."""

    SEED_TEMPLATES = {
        'label_template_stencil_sn': 'sn.tooling',
        'label_template_consumable_sn': 'sn.consumable.info',
        'label_template_equipment_nameplate': 'sn.wsd.device.equipment',
        'label_template_carton': 'sn.wsd.meter.pack.record',
        'label_template_pallet': 'sn.wsd.meter.pack.record',
    }

    ENTRY_VIEWS = {
        'view_sn_tooling_form_print_label': ('sn.tooling', 'form'),
        'view_sn_tooling_list_print_label': ('sn.tooling', 'list'),
        'view_sn_consumable_info_form_print_label': ('sn.consumable.info', 'form'),
        'view_sn_consumable_info_list_print_label': ('sn.consumable.info', 'list'),
        'view_equipment_form_print_label': ('sn.wsd.device.equipment', 'form'),
        'view_equipment_list_print_label': ('sn.wsd.device.equipment', 'list'),
        'view_sn_wsd_meter_pack_record_form_print_label': (
            'sn.wsd.meter.pack.record', 'form'),
        'view_sn_wsd_meter_pack_record_list_print_label': (
            'sn.wsd.meter.pack.record', 'list'),
    }

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reader = cls.env['sn.label.reader']
        cls.renderer = cls.env['sn.label.renderer']

    def test_seed_templates_installed(self):
        for xmlid, model_name in self.SEED_TEMPLATES.items():
            template = self.env.ref(
                f'sn_wsd_label_links.{xmlid}', raise_if_not_found=True)
            self.assertTrue(template.active, xmlid)
            self.assertFalse(template.company_id, xmlid)
            self.assertEqual(template.model_name, model_name, xmlid)
            self.assertGreater(len(template.element_ids), 1, xmlid)
            # every field element resolves against the live model
            for element in template.element_ids:
                if element.content == 'field':
                    self.assertTrue(
                        self.reader.validate_field_path(
                            model_name, element.field_path),
                        f'{xmlid}: {element.field_path}')
                # geometry stays inside the label page
                self.assertGreaterEqual(element.x, 0, xmlid)
                self.assertGreaterEqual(element.y, 0, xmlid)
                self.assertGreaterEqual(element.width, 0, xmlid)
                self.assertGreaterEqual(element.height, 0, xmlid)
                self.assertLessEqual(
                    element.x + element.width, template.width_dots, xmlid)
                self.assertLessEqual(
                    element.y + element.height, template.height_dots, xmlid)

    def test_print_entry_views_installed(self):
        for xmlid, (model_name, view_type) in self.ENTRY_VIEWS.items():
            view = self.env.ref(
                f'sn_wsd_label_links.{xmlid}', raise_if_not_found=True)
            self.assertEqual(view.model, model_name, xmlid)
            self.assertEqual(view.type, view_type, xmlid)
            arch = view.arch_db
            self.assertIn('Print Label', arch, xmlid)
            self.assertIn('sn_wsd_label.action_sn_label_print_wizard', arch, xmlid)
            self.assertIn(f"'{model_name}'", arch, xmlid)

    def test_stencil_label_renders_all_dialects(self):
        """A real sn.tooling chain renders through the seed stencil template
        in ZPL, CPCL-JSON and PNG without errors."""
        tooling_type = self.env['sn.tooling.type'].create({
            'name': 'Stencil',
            'code': 'STENCIL-LINKS',
            'has_tension': True,
        })
        tooling_template = self.env['sn.tooling.template'].create({
            'code': 'TOOL-LINKS-001',
            'name': 'Links Test Stencil',
            'spec': '500x400',
            'type_id': tooling_type.id,
        })
        tooling = self.env['sn.tooling'].create({
            'sn': 'LINKS-STC-0001',
            'template_id': tooling_template.id,
        })
        template = self.env.ref('sn_wsd_label_links.label_template_stencil_sn')
        layout = template._to_layout_dict()

        zpl = self.renderer.render_zpl(layout, tooling)
        self.assertTrue(zpl.startswith('^XA'))
        self.assertTrue(zpl.rstrip().endswith('^XZ'))
        self.assertIn('^PW560', zpl)
        self.assertIn('^LL320', zpl)
        self.assertIn('^BQN,2,', zpl)

        cpcl = self.renderer.render_cpcl_json(layout, tooling)
        tags = [command['tag'] for command in cpcl]
        self.assertIn('INIT', tags)
        self.assertIn('PAGE-WIDTH', tags)
        self.assertIn('QRCODE', tags)

        png = self.renderer.render_png(layout, tooling)
        self.assertTrue(png.startswith(b'\x89PNG'))
        image = Image.open(io.BytesIO(png))
        self.assertEqual(image.size, (560, 320))
