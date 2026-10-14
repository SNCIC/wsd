from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestIssueMaterialLabel(TransactionCase):
    """Issue material labels (领料标签).

    Non-reel materials are issued / transferred by an exact quantity, so the
    label is printed from the operation line (quantity = the issued quantity)
    and reuses the incoming material layout on a stock.move.line bound
    template. Scope: internal transfers (MES material issues included) and
    outgoing deliveries; electronic reel materials and receipts stay out.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.line_side_location = cls.env['stock.location'].create({
            'name': 'Line Side',
            'usage': 'internal',
            'location_id': cls.warehouse.view_location_id.id,
        })
        sequence = cls.env['ir.sequence'].create({
            'name': 'Material Issue: %s' % cls.warehouse.name,
            'code': 'sn.wsd.mes.picking.issue',
            # test-only prefix and high next number: the picking name must not
            # collide with the real MES issue names (stock_picking_name_uniq)
            'prefix': 'TEST/MI/',
            'padding': 4,
            'number_next_actual': 990001,
            'company_id': cls.company.id,
        })
        cls.issue_type = cls.env['stock.picking.type'].create({
            'name': 'Material Issue',
            'code': 'internal',
            'sequence_code': 'sn.wsd.mes.picking.issue',
            'sequence_id': sequence.id,
            'warehouse_id': cls.warehouse.id,
            'company_id': cls.company.id,
            'default_location_src_id': cls.stock_location.id,
            'default_location_dest_id': cls.line_side_location.id,
        })

        cls.product = cls.env['product.product'].create({
            'name': 'MLCC Cap',
            'default_code': 'CAP-001',
            'tracking': 'lot',
            'is_storable': True,
            'material_specification': '0805 100nF',
        })
        cls.reel_category = cls.env['product.category'].create({
            'name': 'Electronic Reels',
            'x_is_reel_material': True,
        })
        cls.reel_product = cls.env['product.product'].create({
            'name': 'Reel Cap',
            'default_code': 'CAP-REEL',
            'tracking': 'lot',
            'is_storable': True,
            'categ_id': cls.reel_category.id,
        })
        cls.lot = cls.env['stock.lot'].create({
            'name': 'CAP-001$S01$B907$100$000001',
            'product_id': cls.product.id,
            'company_id': cls.company.id,
            'supplier_batch_no': 'B907',
            'supplier_name': 'ACME',
            'initial_quantity': 100.5,
        })
        cls.reel_lot = cls.env['stock.lot'].create({
            'name': 'CAP-REEL$S01$B907$5000$000002',
            'product_id': cls.reel_product.id,
            'company_id': cls.company.id,
            'supplier_batch_no': 'B907',
            'initial_quantity': 5000,
        })
        cls.picking = cls._create_picking(cls.issue_type)
        cls.line = cls._create_line(cls.lot, 30)
        cls.reel_line = cls._create_line(cls.reel_lot, 5000)

    @classmethod
    def _create_picking(cls, picking_type, dest_location=None):
        return cls.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': cls.stock_location.id,
            'location_dest_id': (dest_location or cls.line_side_location).id,
            'company_id': cls.company.id,
        })

    @classmethod
    def _create_line(cls, lot, quantity, picking=None, dest_location=None):
        picking = picking or cls.picking
        return cls.env['stock.move.line'].create({
            'picking_id': picking.id,
            'company_id': cls.company.id,
            'product_id': lot.product_id.id,
            'product_uom_id': lot.product_id.uom_id.id,
            'quantity': quantity,
            'location_id': cls.stock_location.id,
            'location_dest_id': (dest_location or cls.line_side_location).id,
            'lot_id': lot.id,
            'lot_name': lot.name,
        })

    def _render_zpl(self, lines):
        report = self.env[
            'report.sn_wsd_stock.report_issue_material_label_zpl']
        return report._get_report_values(lines.ids)['zpl']

    # ------------------------------------------------------------------
    # Seed template
    # ------------------------------------------------------------------
    def test_seed_template_integrity(self):
        template = self.env.ref('sn_wsd_stock.label_template_issue_material')
        self.assertEqual(template.model_id.model, 'stock.move.line')
        self.assertEqual(
            (template.width_dots, template.height_dots, template.dpi),
            (709, 709, 203))
        self.assertEqual(template.sn_field, 'lot_name')
        self.assertFalse(template.company_id)
        # 12 shapes + 7 titles + 7 values + 1 QR + 1 bottom SN, same layout as
        # the incoming material label
        self.assertEqual(len(template.element_ids), 28)
        reader = self.env['sn.label.reader']
        field_elements = template.element_ids.filtered(
            lambda element: element.content == 'field')
        self.assertEqual(len(field_elements), 9)
        for element in field_elements:
            self.assertTrue(
                reader.validate_field_path('stock.move.line', element.field_path))

    # ------------------------------------------------------------------
    # Eligibility
    # ------------------------------------------------------------------
    def test_reel_material_line_is_excluded(self):
        lines = self.picking._issue_material_label_lines()
        self.assertEqual(lines, self.line)
        self.assertFalse(self.reel_line.x_can_print_issue_material_label)
        self.assertTrue(self.line.x_can_print_issue_material_label)

    def test_untracked_and_unissued_lines_are_excluded(self):
        untracked = self.env['product.product'].create({
            'name': 'Solder Wire',
            'default_code': 'SOL-001',
            'is_storable': True,
        })
        untracked_line = self.env['stock.move.line'].create({
            'picking_id': self.picking.id,
            'company_id': self.company.id,
            'product_id': untracked.id,
            'product_uom_id': untracked.uom_id.id,
            'quantity': 3,
            'location_id': self.stock_location.id,
            'location_dest_id': self.line_side_location.id,
        })
        no_lot_line = self.env['stock.move.line'].create({
            'picking_id': self.picking.id,
            'company_id': self.company.id,
            'product_id': self.product.id,
            'product_uom_id': self.product.uom_id.id,
            'quantity': 3,
            'location_id': self.stock_location.id,
            'location_dest_id': self.line_side_location.id,
        })
        zero_qty_line = self.env['stock.move.line'].create({
            'picking_id': self.picking.id,
            'company_id': self.company.id,
            'product_id': self.product.id,
            'product_uom_id': self.product.uom_id.id,
            'quantity': 0,
            'location_id': self.stock_location.id,
            'location_dest_id': self.line_side_location.id,
            'lot_id': self.lot.id,
        })
        lines = self.picking._issue_material_label_lines()
        self.assertEqual(lines, self.line)
        self.assertNotIn(untracked_line, lines)
        self.assertNotIn(no_lot_line, lines)
        self.assertNotIn(zero_qty_line, lines)

    def test_receipt_operation_is_out_of_scope(self):
        receipt_type = self.env['stock.picking.type'].search([
            ('code', '=', 'incoming'),
            ('warehouse_id', '=', self.warehouse.id),
        ], limit=1)
        receipt = self.env['stock.picking'].create({
            'picking_type_id': receipt_type.id,
            'location_id': self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': self.stock_location.id,
            'company_id': self.company.id,
        })
        line = self.env['stock.move.line'].create({
            'picking_id': receipt.id,
            'company_id': self.company.id,
            'product_id': self.product.id,
            'product_uom_id': self.product.uom_id.id,
            'quantity': 10,
            'location_id': self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': self.stock_location.id,
            'lot_id': self.lot.id,
        })
        self.assertFalse(receipt.can_print_issue_material_labels)
        self.assertFalse(line.x_can_print_issue_material_label)
        with self.assertRaises(UserError):
            receipt.action_print_issue_material_labels()
        with self.assertRaises(UserError):
            line.action_print_issue_material_label()

    def test_plain_internal_transfer_is_eligible(self):
        if not self.warehouse.int_type_id:
            self.skipTest('The warehouse has no internal transfer type.')
        picking = self._create_picking(self.warehouse.int_type_id)
        line = self._create_line(self.lot, 12, picking)
        self.assertTrue(picking.can_print_issue_material_labels)
        self.assertTrue(line.x_can_print_issue_material_label)
        self.assertEqual(picking._issue_material_label_lines(), line)
        zpl = self._render_zpl(line)
        self.assertEqual(zpl.count('^XA'), 1)
        self.assertIn('^FD12^FS', zpl)

    def test_outgoing_delivery_is_eligible(self):
        if not self.warehouse.out_type_id:
            self.skipTest('The warehouse has no outgoing delivery type.')
        customers = self.env.ref('stock.stock_location_customers')
        picking = self._create_picking(self.warehouse.out_type_id, customers)
        line = self._create_line(self.lot, 8.5, picking, customers)
        self.assertTrue(picking.can_print_issue_material_labels)
        self.assertTrue(line.x_can_print_issue_material_label)
        self.assertEqual(picking._issue_material_label_lines(), line)
        zpl = self._render_zpl(line)
        self.assertEqual(zpl.count('^XA'), 1)
        self.assertIn('^FD8.5^FS', zpl)
        # the label location is the last segment of the delivery destination
        # (rendered as a bitmap when the location name is not ASCII)
        self.assertEqual(
            line.material_label_location,
            customers.complete_name.rsplit('/', 1)[-1].strip())

    def test_manufacturing_operation_is_out_of_scope(self):
        if not self.warehouse.manu_type_id:
            self.skipTest('The warehouse has no manufacturing operation type.')
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.warehouse.manu_type_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.stock_location.id,
            'company_id': self.company.id,
        })
        self.assertFalse(picking._is_issue_material_label_picking())
        self.assertFalse(picking.can_print_issue_material_labels)

    def test_cancelled_operation_is_out_of_scope(self):
        picking = self._create_picking(self.warehouse.int_type_id)
        self._create_line(self.lot, 5, picking)
        self.assertTrue(picking.can_print_issue_material_labels)
        picking.write({'state': 'cancel'})
        self.assertFalse(picking.can_print_issue_material_labels)
        with self.assertRaises(UserError):
            picking.action_print_issue_material_labels()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def test_picking_action_renders_one_label_per_line(self):
        second_line = self._create_line(self.lot, 5.5)
        self.assertTrue(self.picking.can_print_issue_material_labels)
        action = self.picking.action_print_issue_material_labels()
        self.assertEqual(action['type'], 'ir.actions.report')
        self.assertTrue(action['close_on_report_download'])

        lines = self.picking._issue_material_label_lines()
        self.assertEqual(lines, self.line + second_line)
        zpl = self._render_zpl(lines)
        self.assertEqual(zpl.count('^XA'), 2)
        self.assertEqual(zpl.count('^XZ'), 2)
        # quantity cell prints the issued quantity, not the batch quantity
        self.assertEqual(zpl.count('^FD30^FS'), 1)
        self.assertEqual(zpl.count('^FD5.5^FS'), 1)
        self.assertNotIn('^FD100.5^FS', zpl)
        self.assertIn('^FDCAP-001^FS', zpl)
        self.assertIn('^FDB907^FS', zpl)
        self.assertIn('^FDACME^FS', zpl)
        self.assertIn('^FDLine Side^FS', zpl)
        self.assertIn(f'^FD{self.lot.name}^FS', zpl)

    def test_single_line_action_renders_one_label(self):
        action = self.line.action_print_issue_material_label()
        self.assertEqual(action['type'], 'ir.actions.report')
        self.assertTrue(action['close_on_report_download'])
        zpl = self._render_zpl(self.line)
        self.assertEqual(zpl.count('^XA'), 1)
        self.assertIn('^FO20,20^GB669,669,3^FS', zpl)
        self.assertIn('^FO453,245^GFA', zpl)
        self.assertIn('^FD30^FS', zpl)

    def test_qweb_text_download_payload(self):
        rendered, report_type = self.env['ir.actions.report']._render_qweb_text(
            'sn_wsd_stock.action_report_issue_material_label_zpl',
            self.line.ids, {},
        )
        self.assertEqual(report_type, 'text')
        payload = rendered.decode('utf-8') if isinstance(rendered, bytes) else rendered
        self.assertIn('^XA', payload)
        self.assertIn('^FD30^FS', payload)

    def test_report_skips_ineligible_lines(self):
        # the report is also bound to stock.move.line (Print menu): a reel
        # material selected by mistake is skipped, eligible lines still print
        zpl = self._render_zpl(self.line + self.reel_line)
        self.assertEqual(zpl.count('^XA'), 1)
        self.assertIn('^FD30^FS', zpl)
        logs = self.env['sn.label.print.log'].search([
            ('res_model', '=', 'stock.move.line'),
            ('res_id', 'in', (self.line + self.reel_line).ids),
        ])
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs.res_id, self.line.id)
        self.assertEqual(
            logs.template_id,
            self.env.ref('sn_wsd_stock.label_template_issue_material'))
        self.assertEqual(logs.copies, 1)
        self.assertEqual(logs.user_id, self.env.user)

    def test_nothing_eligible_raises_user_error(self):
        with self.assertRaises(UserError):
            self._render_zpl(self.reel_line)

    def test_location_is_the_operation_destination(self):
        self.assertEqual(self.line.material_label_location, 'Line Side')
        self.line.location_dest_id = self.stock_location
        self.assertEqual(
            self.line.material_label_location,
            self.stock_location.complete_name.rsplit('/', 1)[-1].strip())

    def test_no_lines_raises_user_error(self):
        report = self.env[
            'report.sn_wsd_stock.report_issue_material_label_zpl']
        with self.assertRaises(UserError):
            report._get_report_values([])
