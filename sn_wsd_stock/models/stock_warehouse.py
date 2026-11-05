from odoo import _, fields, models


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    sn_unstored_return_type_id = fields.Many2one(
        'stock.picking.type',
        string='Vendor Return Type',
        copy=False,
        check_company=True,
        help="Operation type used to return received goods to the vendor, "
             "either before they are stored (no batch yet) or after (the "
             "stored batch is reused).",
    )
    other_in_type_id = fields.Many2one(
        'stock.picking.type',
        string='Other Receipt Type',
        copy=False,
        check_company=True,
        help="Operation type of the other receipts: goods entering the stock "
             "through the inventory adjustment location, without a purchase "
             "order.",
    )
    other_out_type_id = fields.Many2one(
        'stock.picking.type',
        string='Other Delivery Type',
        copy=False,
        check_company=True,
        help="Operation type of the other deliveries: goods leaving the stock "
             "through the inventory adjustment location, without a sales "
             "order.",
    )
    sn_inventory_loss_type_id = fields.Many2one(
        'stock.picking.type',
        string='Inventory Loss Type',
        copy=False,
        check_company=True,
        help="Operation type of the inventory losses: goods leaving the stock "
             "on the inventory loss location, whose valuation account books "
             "the loss of the difference.",
    )
    sn_inventory_gain_type_id = fields.Many2one(
        'stock.picking.type',
        string='Inventory Gain Type',
        copy=False,
        check_company=True,
        help="Operation type of the inventory gains: goods entering the stock "
             "from the inventory gain location, whose valuation account books "
             "the gain of the difference.",
    )
    sn_consignment_in_type_id = fields.Many2one(
        'stock.picking.type',
        string='Consignment Receipt Type',
        copy=False,
        check_company=True,
        help="Operation type of the consignment receipts: goods provided by "
             "the customer and stored for that customer, entering the stock "
             "without a purchase order and going through the quality control "
             "and storage operations of the reception.",
    )
    sn_outsourcing_issue_type_id = fields.Many2one(
        'stock.picking.type',
        string='Outsourcing Issue Type',
        copy=False,
        check_company=True,
        help="Operation type of the outsourcing issues: goods sent out to a "
             "subcontractor. The operation type is created by hand, so it is "
             "linked here rather than created with the warehouse.",
    )

    def _pre_putaway_lot_settings(self):
        """Lot handling of the operations preceding the storage transfer.

        With a two- or three-step reception the goods move through the input
        and quality control locations before the internal batches exist: the
        batches are generated at putaway, where the quantity per label splits
        the lines. Odoo requires a lot on every operation managing lots, so
        both lot options are disabled on those upstream operation types, which
        is how Odoo knows the operation does not manage lots at all. The
        receipt of a one-step reception keeps creating lots: there it is the
        operation generating the labels.
        """
        self.ensure_one()
        if self.reception_steps == 'one_step':
            return {'in_type_id': {
                'use_create_lots': True,
                'use_existing_lots': False,
            }}
        no_lots = {
            'use_create_lots': False,
            'use_existing_lots': False,
        }
        return {
            'in_type_id': dict(no_lots),
            'qc_type_id': dict(no_lots),
        }

    def _get_unstored_return_create_values(self):
        """Values of the operation returning goods to the vendor.

        Goods sent back before putaway never received an internal batch, so
        the return operation must not require one: both lot options are
        disabled, which is how Odoo knows an operation does not manage lots.
        The goods already stored keep their batch anyway, because the
        reservation puts it on the move line, so the stock is still decreased
        on the right batch.
        """
        self.ensure_one()
        supplier_location = self.env.ref('stock.stock_location_suppliers')
        return {
            'name': _('Return to Vendor'),
            'code': 'outgoing',
            'sequence_code': 'RTV',
            'use_create_lots': False,
            'use_existing_lots': False,
            'default_location_src_id': self.wh_input_stock_loc_id.id,
            'default_location_dest_id': supplier_location.id,
            'active': self.reception_steps != 'one_step',
            'company_id': self.company_id.id,
        }

    def _ensure_unstored_return_type(self):
        """Return the vendor return operation, creating it when missing.

        The operation type is normally created with the warehouse, but a
        warehouse installed before this feature only gets it once the
        warehouse is written. Creating it lazily keeps the module upgrade
        safe: the barcode module adds required columns to the operation types
        and is loaded after this one, so creating an operation type during the
        upgrade of this module would violate those constraints.
        """
        self.ensure_one()
        if self.sn_unstored_return_type_id.active:
            return self.sn_unstored_return_type_id
        warehouse = self.sudo()
        values = warehouse._create_or_update_sequences_and_picking_types()
        if values:
            warehouse.write(values)
        return self.sn_unstored_return_type_id

    def _get_consignment_in_create_values(self):
        """Values of the consignment receipt operation.

        The consigned goods enter the stock without a purchase order: they
        are provided by the customer and only stored for that customer, so the
        operation starts on the supplier location like a purchase receipt. A
        multi-step reception lands on the input location, which is what makes
        the quality control and storage operations follow (the push rules are
        read on the destination location, not on the operation type).
        """
        self.ensure_one()
        supplier_location = self.env.ref('stock.stock_location_suppliers')
        destination = (
            self.wh_input_stock_loc_id
            if self.reception_steps != 'one_step'
            else self.lot_stock_id
        )
        return {
            'name': _('Consignment Receipts'),
            'code': 'incoming',
            'sequence_code': 'CIN',
            'barcode': self.code.replace(" ", "").upper() + 'CIN',
            'default_location_src_id': supplier_location.id,
            'default_location_dest_id': destination.id,
            'company_id': self.company_id.id,
        }

    def _ensure_consignment_in_type(self):
        """Return the consignment receipt operation, creating it when missing.

        The operation type is created with the warehouse, but a warehouse
        installed before this feature only gets it once the warehouse is
        written. Creating it lazily keeps the module upgrade safe: the barcode
        module adds required columns to the operation types and is loaded
        after this one.
        """
        self.ensure_one()
        if self.sn_consignment_in_type_id.active:
            return self.sn_consignment_in_type_id
        warehouse = self.sudo()
        values = warehouse._create_or_update_sequences_and_picking_types()
        if values:
            warehouse.write(values)
        return self.sn_consignment_in_type_id

    def _get_inventory_operation_create_values(self, kind):
        """Values of the inventory loss and inventory gain operations.

        A loss takes the goods out of the stock and a gain brings them in, so
        they use the outgoing and the incoming codes and mirror each other.
        Both take the inventory adjustment location as their external end, the
        way the other receipts and deliveries do: the difference goes through
        the same virtual location as the inventory adjustment of the products,
        whose valuation account books the loss or the gain.
        """
        self.ensure_one()
        adjustment_location = self._get_inventory_adjustment_location()
        if kind == 'loss':
            name = _('Inventory Losses')
            code = 'outgoing'
            sequence_code = 'IVL'
            src_location = self.lot_stock_id
            dest_location = (
                adjustment_location
                or self.env.ref('stock.stock_location_customers'))
        else:
            name = _('Inventory Gains')
            code = 'incoming'
            sequence_code = 'IVG'
            src_location = (
                adjustment_location
                or self.env.ref('stock.stock_location_suppliers'))
            dest_location = self.lot_stock_id
        return {
            'name': name,
            'code': code,
            'sequence_code': sequence_code,
            'default_location_src_id': src_location.id,
            'default_location_dest_id': dest_location.id,
            'barcode': self.code.replace(" ", "").upper() + sequence_code,
            'company_id': self.company_id.id,
            # The difference is booked on the batches already carrying the
            # stock: the operation neither creates nor requires a new batch.
            'use_create_lots': False,
            'use_existing_lots': True,
        }

    def _ensure_inventory_operation_type(self, kind):
        """Return the inventory loss or gain operation, creating it if needed.

        The operation types are created with the warehouse, but a warehouse
        installed before this feature only gets them once the warehouse is
        written. Creating them lazily keeps the module upgrade safe: the
        barcode module adds required columns to the operation types and is
        loaded after this one.
        """
        self.ensure_one()
        field_name = (
            'sn_inventory_loss_type_id'
            if kind == 'loss'
            else 'sn_inventory_gain_type_id'
        )
        if self[field_name].active:
            return self[field_name]
        warehouse = self.sudo()
        values = warehouse._create_or_update_sequences_and_picking_types()
        if values:
            warehouse.write(values)
        return self[field_name]

    def _get_picking_type_update_values(self):
        values = super()._get_picking_type_update_values()
        for picking_type, lot_settings in (
                self._pre_putaway_lot_settings().items()):
            values.setdefault(picking_type, {}).update(lot_settings)
        values['sn_unstored_return_type_id'] = {
            'active': self.reception_steps != 'one_step',
        }
        supplier_location = self.env.ref('stock.stock_location_suppliers')
        values['sn_consignment_in_type_id'] = {
            'active': self.active,
            'default_location_src_id': supplier_location.id,
            'default_location_dest_id': (
                self.wh_input_stock_loc_id
                if self.reception_steps != 'one_step'
                else self.lot_stock_id).id,
        }
        adjustment_location = self._get_inventory_adjustment_location()
        values['other_in_type_id'] = {
            'active': self.active,
            'default_location_src_id': (
                adjustment_location
                or self.env.ref('stock.stock_location_suppliers')).id,
            'default_location_dest_id': self.lot_stock_id.id,
        }
        values['other_out_type_id'] = {
            'active': self.active,
            'default_location_src_id': self.lot_stock_id.id,
            'default_location_dest_id': (
                adjustment_location
                or self.env.ref('stock.stock_location_customers')).id,
        }
        values['sn_inventory_loss_type_id'] = {
            'active': self.active,
            'default_location_src_id': self.lot_stock_id.id,
            'default_location_dest_id': (
                adjustment_location
                or self.env.ref('stock.stock_location_customers')).id,
        }
        values['sn_inventory_gain_type_id'] = {
            'active': self.active,
            'default_location_src_id': (
                adjustment_location
                or self.env.ref('stock.stock_location_suppliers')).id,
            'default_location_dest_id': self.lot_stock_id.id,
        }
        return values

    def _get_inventory_adjustment_location(self):
        """Inventory adjustment location the other operations end on.

        The location is read by name, not on its usage: a database carrying
        the virtual locations of the other operations has several locations
        with the ``inventory`` usage, and the inventory adjustment one is not
        the first on ``complete_name`` any more.
        """
        self.ensure_one()
        return self.env['stock.location']._sn_get_inventory_adjustment_location(
            self.company_id)

    def _get_picking_type_create_values(self, max_sequence):
        values, max_sequence = super()._get_picking_type_create_values(
            max_sequence)
        for picking_type, lot_settings in (
                self._pre_putaway_lot_settings().items()):
            values.setdefault(picking_type, {}).update(lot_settings)
        values['sn_unstored_return_type_id'] = dict(
            self._get_unstored_return_create_values(),
            sequence=max_sequence,
        )
        values['other_in_type_id'] = dict(
            self._get_other_operation_create_values('in'),
            sequence=max_sequence + 1,
        )
        values['other_out_type_id'] = dict(
            self._get_other_operation_create_values('out'),
            sequence=max_sequence + 2,
        )
        values['sn_consignment_in_type_id'] = dict(
            self._get_consignment_in_create_values(),
            sequence=max_sequence + 3,
        )
        values['sn_inventory_loss_type_id'] = dict(
            self._get_inventory_operation_create_values('loss'),
            sequence=max_sequence + 4,
        )
        values['sn_inventory_gain_type_id'] = dict(
            self._get_inventory_operation_create_values('gain'),
            sequence=max_sequence + 5,
        )
        return values, max_sequence + 6

    def _get_other_operation_create_values(self, kind):
        """Values of the other receipt and other delivery operations.

        Both take the inventory adjustment location as their external end:
        the goods come from the outside without a purchase order and leave
        without a sales order, the way the Kingdee other documents do.
        """
        self.ensure_one()
        adjustment_location = self._get_inventory_adjustment_location()
        if kind == 'in':
            name = _('Other Receipts')
            code = 'incoming'
            sequence_code = 'OIN'
            src_location = (
                adjustment_location
                or self.env.ref('stock.stock_location_suppliers'))
            dest_location = self.lot_stock_id
        else:
            name = _('Other Deliveries')
            code = 'outgoing'
            sequence_code = 'OOUT'
            src_location = self.lot_stock_id
            dest_location = (
                adjustment_location
                or self.env.ref('stock.stock_location_customers'))
        return {
            'name': name,
            'code': code,
            'sequence_code': sequence_code,
            'default_location_src_id': src_location.id,
            'default_location_dest_id': dest_location.id,
            'barcode': self.code.replace(" ", "").upper() + sequence_code,
            'company_id': self.company_id.id,
        }

    def _get_sequence_values(self, name=False, code=False):
        values = super()._get_sequence_values(name=name, code=code)
        name = name if name else self.name
        code = code if code else self.code
        values['sn_unstored_return_type_id'] = {
            'name': _('%(name)s Sequence vendor return', name=name),
            'prefix': code + '/' + (
                self.sn_unstored_return_type_id.sequence_code or 'RTV') + '/',
            'padding': 5,
            'company_id': self.company_id.id,
        }
        values['other_in_type_id'] = {
            'name': _('%(name)s Sequence other receipts', name=name),
            'prefix': code + '/' + (
                self.other_in_type_id.sequence_code or 'OIN') + '/',
            'padding': 5,
            'company_id': self.company_id.id,
        }
        values['other_out_type_id'] = {
            'name': _('%(name)s Sequence other deliveries', name=name),
            'prefix': code + '/' + (
                self.other_out_type_id.sequence_code or 'OOUT') + '/',
            'padding': 5,
            'company_id': self.company_id.id,
        }
        values['sn_consignment_in_type_id'] = {
            'name': _('%(name)s Sequence consignment receipts', name=name),
            'prefix': code + '/' + (
                self.sn_consignment_in_type_id.sequence_code or 'CIN') + '/',
            'padding': 5,
            'company_id': self.company_id.id,
        }
        values['sn_inventory_loss_type_id'] = {
            'name': _('%(name)s Sequence inventory losses', name=name),
            'prefix': code + '/' + (
                self.sn_inventory_loss_type_id.sequence_code or 'IVL') + '/',
            'padding': 5,
            'company_id': self.company_id.id,
        }
        values['sn_inventory_gain_type_id'] = {
            'name': _('%(name)s Sequence inventory gains', name=name),
            'prefix': code + '/' + (
                self.sn_inventory_gain_type_id.sequence_code or 'IVG') + '/',
            'padding': 5,
            'company_id': self.company_id.id,
        }
        return values
