from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestIqcArrivalBatch(TransactionCase):
    """The printed inspection record quotes the arrival batch.

    With a multi-step reception the supplier batch is read on the reels at
    putaway, after the inspection, so the record falls back on the arrival
    batch instead of leaving the production batch blank.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.product = cls.env['product.product'].create({
            'name': 'IQC Reel',
            'default_code': 'IQC-900',
            'tracking': 'lot',
            'is_storable': True,
        })
        cls.supplier_location = cls.env.ref('stock.stock_location_suppliers')
        cls.arrival_date = fields.Datetime.to_datetime('2026-10-12 08:30:00')

    def _move(self, picking, location, location_dest, quantity=10):
        return self.env['stock.move'].create({
            'product_id': self.product.id,
            'product_uom_qty': quantity,
            'product_uom': self.product.uom_id.id,
            'picking_id': picking.id,
            'location_id': location.id,
            'location_dest_id': location_dest.id,
        })

    def _receipt(self):
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.warehouse.in_type_id.id,
            'location_id': self.supplier_location.id,
            'location_dest_id': self.warehouse.lot_stock_id.id,
        })
        self._move(
            picking, self.supplier_location, self.warehouse.lot_stock_id)
        # The scheduled date is computed from the moves: set it once they
        # exist so the arrival date is the one the report must quote.
        picking.scheduled_date = self.arrival_date
        return picking

    def _inspection(self, picking, lot=False):
        return self.env['sn.wsd.quality.inspection'].create({
            'inspection_type': 'iqc',
            'picking_id': picking.id,
            'product_id': self.product.id,
            'lot_id': lot.id if lot else False,
        })

    def test_report_quotes_the_arrival_batch_when_no_batch_is_known(self):
        inspection = self._inspection(self._receipt())
        self.assertEqual(
            inspection._get_iqc_supplier_batch_no(),
            self.arrival_date.strftime('%Y%m%d'),
        )
        self.assertEqual(inspection.lot_id, self.env['stock.lot'])

    def test_report_quotes_the_receipt_behind_the_quality_transfer(self):
        receipt = self._receipt()
        quality_picking = self.env['stock.picking'].create({
            'picking_type_id': self.warehouse.int_type_id.id,
            'location_id': self.warehouse.lot_stock_id.id,
            'location_dest_id': self.warehouse.lot_stock_id.id,
        })
        quality_move = self._move(
            quality_picking,
            self.warehouse.lot_stock_id,
            self.warehouse.lot_stock_id,
        )
        quality_move.move_orig_ids = receipt.move_ids

        inspection = self._inspection(quality_picking)
        self.assertEqual(
            inspection._get_iqc_receipt_picking(),
            receipt,
        )
        self.assertEqual(
            inspection._get_iqc_supplier_batch_no(),
            self.arrival_date.strftime('%Y%m%d'),
        )

    def test_report_quotes_the_recorded_supplier_batch(self):
        inspection = self._inspection(self._receipt())
        inspection.lot_id = self.env['stock.lot'].create({
            'name': 'IQC-900$SUP-01$B907$10$000001',
            'product_id': self.product.id,
            'supplier_batch_no': 'B907',
        })
        self.assertEqual(inspection._get_iqc_supplier_batch_no(), 'B907')
