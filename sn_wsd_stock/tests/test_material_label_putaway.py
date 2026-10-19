from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMaterialLabelPutaway(TransactionCase):
    """Internal batches are generated on the operation storing the goods.

    With a three-step reception the quantity per label that splits the goods
    is decided on the storage transfer (quality -> stock), never on the
    receipt or on the quality control transfer: their lots would travel on the
    quants and could no longer be re-split.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.warehouse.reception_steps = 'three_steps'
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Label Supplier',
            'ref': 'SUP-01',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Reel Capacitor',
            'default_code': 'CAP-900',
            'tracking': 'lot',
            'is_storable': True,
        })
        cls.supplier_location = cls.env.ref('stock.stock_location_suppliers')

    def _create_move(self, picking_type, location, location_dest, quantity):
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'partner_id': self.supplier.id,
            'location_id': location.id,
            'location_dest_id': location_dest.id,
        })
        move = self.env['stock.move'].create({
            'product_id': self.product.id,
            'product_uom_qty': quantity,
            'product_uom': self.product.uom_id.id,
            'picking_id': picking.id,
            'location_id': location.id,
            'location_dest_id': location_dest.id,
        })
        move._action_confirm()
        return move

    def _add_line(self, move, quantity):
        return self.env['stock.move.line'].create({
            'move_id': move.id,
            'picking_id': move.picking_id.id,
            'product_id': self.product.id,
            'product_uom_id': self.product.uom_id.id,
            'quantity': quantity,
            'location_id': move.location_id.id,
            'location_dest_id': move.location_dest_id.id,
        })

    def _line(self, move, quantity):
        """Operation line of the move, created when it carries none.

        A receipt already has one: its supplier source bypasses the
        reservation and confirming the move creates the line. The storage
        transfer gets its line from the reservation of the goods sitting in
        the quality control area.
        """
        return move.move_line_ids[:1] or self._add_line(move, quantity)

    def _storage_move(self, quantity):
        self.env['stock.quant']._update_available_quantity(
            self.product, self.warehouse.wh_qc_stock_loc_id, quantity,
        )
        move = self._create_move(
            self.warehouse.store_type_id,
            self.warehouse.wh_qc_stock_loc_id,
            self.warehouse.lot_stock_id,
            quantity,
        )
        move._action_assign()
        self._line(move, quantity)
        return move

    def test_three_steps_only_store_generates(self):
        receipt_move = self._create_move(
            self.warehouse.in_type_id,
            self.supplier_location,
            self.warehouse.wh_input_stock_loc_id,
            100,
        )
        self.assertFalse(receipt_move.x_can_generate_material_labels)
        with self.assertRaises(UserError):
            receipt_move.action_generate_material_labels()

        quality_move = self._create_move(
            self.warehouse.qc_type_id,
            self.warehouse.wh_input_stock_loc_id,
            self.warehouse.wh_qc_stock_loc_id,
            100,
        )
        self.assertFalse(quality_move.x_can_generate_material_labels)

        storage_move = self._storage_move(100)
        self.assertTrue(storage_move.x_can_generate_material_labels)

    def test_one_step_receipt_still_generates(self):
        warehouse = self.env['stock.warehouse'].create({
            'name': 'One Step Warehouse',
            'code': 'OSWH',
            'reception_steps': 'one_step',
        })
        receipt_move = self._create_move(
            warehouse.in_type_id,
            self.supplier_location,
            warehouse.lot_stock_id,
            100,
        )
        self.assertTrue(receipt_move.x_can_generate_material_labels)

    def test_pre_putaway_transfers_do_not_require_a_lot(self):
        self.assertFalse(self.warehouse.in_type_id.use_create_lots)
        self.assertFalse(self.warehouse.in_type_id.use_existing_lots)
        self.assertFalse(self.warehouse.qc_type_id.use_create_lots)
        self.assertFalse(self.warehouse.qc_type_id.use_existing_lots)
        self.assertTrue(self.warehouse.store_type_id.use_existing_lots)

    def test_three_step_receipt_validates_without_a_lot(self):
        move = self._create_move(
            self.warehouse.in_type_id,
            self.supplier_location,
            self.warehouse.wh_input_stock_loc_id,
            10,
        )
        picking = move.picking_id
        self._line(move, 10).write({'quantity': 10, 'picked': True})
        picking.button_validate()
        self.assertEqual(picking.state, 'done')

    def test_quantity_per_label_splits_on_storage(self):
        move = self._storage_move(140000)
        move.move_line_ids.write({
            'supplier_batch_no': 'B907',
            'quantity_per_label': 10000,
        })
        move.action_generate_material_labels()

        self.assertEqual(len(move.move_line_ids), 14)
        self.assertEqual(len(move.move_line_ids.lot_id), 14)
        self.assertEqual(set(move.move_line_ids.mapped('quantity')), {10000})
        for lot in move.move_line_ids.lot_id:
            self.assertEqual(
                lot.name.split('$')[:4],
                ['CAP-900', 'SUP-01', 'B907', '10000'],
            )
        self.assertEqual(
            sum(move.move_line_ids.mapped('lot_id.initial_quantity')),
            140000,
        )

    def test_remainder_gets_its_own_label(self):
        move = self._storage_move(140000)
        move.move_line_ids.quantity_per_label = 60000
        move.action_generate_material_labels()
        self.assertEqual(
            sorted(move.move_line_ids.mapped('quantity')),
            [20000, 60000, 60000],
        )

    def test_supplier_batch_is_read_at_putaway(self):
        """The receipt leaves the batch empty: the reels decide it later."""
        receipt_move = self._create_move(
            self.warehouse.in_type_id,
            self.supplier_location,
            self.warehouse.wh_input_stock_loc_id,
            100,
        )
        receipt_line = self._line(receipt_move, 100)
        self.assertFalse(receipt_line.supplier_batch_no)

        storage_move = self._storage_move(100)
        today = fields.Date.context_today(self).strftime('%Y%m%d')
        self.assertEqual(storage_move.move_line_ids.supplier_batch_no, today)

    def test_supplier_batch_split_across_reels(self):
        """Two batches of one delivery: one line each, own labels each."""
        move = self._storage_move(100)
        first_line = move.move_line_ids
        first_line.write({
            'quantity': 40,
            'supplier_batch_no': 'B907',
            'quantity_per_label': 20,
        })
        self._add_line(move, 60).write({
            'supplier_batch_no': 'B908',
            'quantity_per_label': 30,
        })
        move.action_generate_material_labels()

        self.assertEqual(len(move.move_line_ids), 4)
        self.assertEqual(
            sorted(move.move_line_ids.mapped('quantity')),
            [20, 20, 30, 30],
        )
        self.assertEqual(
            sorted(set(move.move_line_ids.lot_id.mapped('supplier_batch_no'))),
            ['B907', 'B908'],
        )

    def test_revoke_merges_the_lines_back(self):
        move = self._storage_move(140000)
        move.move_line_ids.write({
            'supplier_batch_no': 'B907',
            'quantity_per_label': 10000,
        })
        move.action_generate_material_labels()
        lots = move.move_line_ids.lot_id

        move.action_revoke_material_labels()

        self.assertEqual(len(move.move_line_ids), 1)
        self.assertFalse(move.move_line_ids.lot_id)
        self.assertEqual(move.move_line_ids.quantity, 140000)
        self.assertEqual(move.move_line_ids.supplier_batch_no, 'B907')
        self.assertFalse(lots.exists())

    def test_printed_or_consumed_batches_cannot_be_revoked(self):
        move = self._storage_move(100)
        move.move_line_ids.quantity_per_label = 50
        move.action_generate_material_labels()
        move.move_line_ids.lot_id.write({'label_print_count': 1})

        with self.assertRaises(UserError):
            move.action_revoke_material_labels()
        with self.assertRaises(ValidationError):
            move.move_line_ids.quantity = 40
