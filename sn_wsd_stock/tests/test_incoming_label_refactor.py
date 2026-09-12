from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestIncomingLabelRefactor(TransactionCase):
    """label-center batch 5: incoming material labels are rendered by the
    sn_wsd_label engine from the seed template, keeping the former report
    entry point, output shape and label_print_count bookkeeping."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env['product.product'].create({
            'name': 'MLCC Cap',
            'default_code': 'CAP-001',
            'tracking': 'lot',
            'is_storable': True,
            'material_specification': '0805 100nF',
        })
        cls.lot = cls.env['stock.lot'].create({
            'name': 'CAP-001$S01$B907$100$000001',
            'product_id': cls.product.id,
            'supplier_batch_no': 'B907',
            'supplier_name': 'ACME',
            'initial_quantity': 100.5,
        })

    def _render_zpl(self, lots):
        report = self.env['report.sn_wsd_stock.report_incoming_material_label_zpl']
        return report._get_report_values(lots.ids)['zpl']

    def test_seed_template_integrity(self):
        template = self.env.ref('sn_wsd_stock.label_template_incoming_material')
        self.assertEqual(template.model_id.model, 'stock.lot')
        self.assertEqual((template.width_dots, template.height_dots, template.dpi),
                         (709, 709, 203))
        self.assertEqual(template.sn_field, 'name')
        self.assertFalse(template.company_id)
        # 11 shapes + 7 titles + 7 values + 1 QR + 1 bottom SN
        self.assertEqual(len(template.element_ids), 27)
        # every seeded field path resolves on the live registry (the
        # product_* elements are stock.lot bridge relateds over
        # sn_wsd_mrp's material_specification / core product fields)
        reader = self.env['sn.label.reader']
        field_elements = template.element_ids.filtered(
            lambda element: element.content == 'field')
        self.assertEqual(len(field_elements), 9)
        for element in field_elements:
            self.assertTrue(
                reader.validate_field_path('stock.lot', element.field_path))

    def test_report_renders_engine_zpl(self):
        zpl = self._render_zpl(self.lot)
        self.assertTrue(zpl.startswith('^XA'))
        self.assertTrue(zpl.rstrip().endswith('^XZ'))
        self.assertIn('^PW709', zpl)
        self.assertIn('^LL709', zpl)
        # outer frame and grid lines translated 1:1 from the old template
        self.assertIn('^FO20,20^GB669,669,3^FS', zpl)
        self.assertIn('^FO20,128^GB669,3,3^FS', zpl)
        self.assertIn('^FO20,236^GB414,3,3^FS', zpl)
        self.assertIn('^FO20,344^GB414,3,3^FS', zpl)
        self.assertIn('^FO20,452^GB669,3,3^FS', zpl)
        self.assertIn('^FO20,560^GB669,3,3^FS', zpl)
        self.assertIn('^FO146,20^GB3,432,3^FS', zpl)
        self.assertIn('^FO434,20^GB3,432,3^FS', zpl)
        self.assertIn('^FO508,20^GB3,216,3^FS', zpl)
        self.assertIn('^FO434,236^GB255,3,3^FS', zpl)
        self.assertIn('^FO434,236^GB3,216,3^FS', zpl)
        # QR code remains a server-side bitmap in the resized QR region,
        # not a native ^BQ command
        self.assertIn('^FO453,245^GFA', zpl)
        self.assertNotIn('^BQ', zpl)
        # titles and field values
        self.assertIn('^FDMaterial Code^FS', zpl)
        self.assertIn('^FDBatch^FS', zpl)
        self.assertIn('^FDSpecification^FS', zpl)
        self.assertIn('^FDCAP-001^FS', zpl)
        self.assertIn('^FDB907^FS', zpl)
        self.assertIn('^FDMLCC Cap^FS', zpl)
        self.assertIn('^FD100.5^FS', zpl)
        self.assertIn('^FD0805 100nF^FS', zpl)
        self.assertIn('^FDACME^FS', zpl)
        self.assertIn('^FDLocation^FS', zpl)
        self.assertIn(f'^FD{self.lot.name}^FS', zpl)

    def test_qweb_text_download_payload(self):
        rendered, report_type = self.env['ir.actions.report']._render_qweb_text(
            'sn_wsd_stock.action_report_incoming_material_label_zpl',
            self.lot.ids, {},
        )
        self.assertEqual(report_type, 'text')
        payload = rendered.decode('utf-8') if isinstance(rendered, bytes) else rendered
        self.assertIn('^XA', payload)
        self.assertIn('^FO20,20^GB669,669,3^FS', payload)
        self.assertIn('^FO453,245^GFA', payload)
        self.assertEqual(self.lot.label_print_count, 1)

    def test_label_print_count_increments(self):
        self.assertEqual(self.lot.label_print_count, 0)
        self._render_zpl(self.lot)
        self.assertEqual(self.lot.label_print_count, 1)
        self._render_zpl(self.lot)
        self.assertEqual(self.lot.label_print_count, 2)

    def test_print_audit_written_per_lot(self):
        self._render_zpl(self.lot)
        logs = self.env['sn.label.print.log'].search([
            ('res_model', '=', 'stock.lot'),
            ('res_id', '=', self.lot.id),
        ])
        self.assertEqual(len(logs), 1)
        self.assertEqual(
            logs.template_id,
            self.env.ref('sn_wsd_stock.label_template_incoming_material'))
        self.assertEqual(logs.copies, 1)
        self.assertEqual(logs.user_id, self.env.user)

    def test_multiple_lots_one_label_each(self):
        second_lot = self.env['stock.lot'].create({
            'name': 'CAP-001$S01$B907$100$000002',
            'product_id': self.product.id,
            'supplier_batch_no': 'B907',
            'supplier_name': 'ACME',
            'initial_quantity': 50,
        })
        lots = self.lot + second_lot
        zpl = self._render_zpl(lots)
        self.assertEqual(zpl.count('^XA'), 2)
        self.assertEqual(zpl.count('^XZ'), 2)
        self.assertEqual(lots.mapped('label_print_count'), [1, 1])

    def test_no_lots_raises_user_error(self):
        report = self.env['report.sn_wsd_stock.report_incoming_material_label_zpl']
        with self.assertRaises(UserError):
            report._get_report_values([])

    def test_render_in_zh_cn_lang_context(self):
        # titles are translate=True fixed texts: rendering under a Chinese
        # user language must switch to bitmap output without errors
        self.env['res.lang']._activate_lang('zh_CN')
        report = self.env[
            'report.sn_wsd_stock.report_incoming_material_label_zpl'
        ].with_context(lang='zh_CN')
        zpl = report._get_report_values(self.lot.ids)['zpl']
        self.assertTrue(zpl.startswith('^XA'))
        self.assertIn('^FO20,20^GB669,669,3^FS', zpl)
        self.assertIn('^FO453,308^GFA', zpl)
