from odoo import _, fields, models


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    sn_unstored_return_type_id = fields.Many2one(
        'stock.picking.type',
        string='Not Stored Return Type',
        copy=False,
        check_company=True,
        help="Operation type used to return goods to the vendor before they "
             "are stored, i.e. before the internal batches are generated.",
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
        """Values of the return operation preceding the storage transfer.

        Goods sent back before putaway never received an internal batch, so
        the return operation must not manage lots either. Both lot options are
        disabled, which is Odoo's way of saying an operation does not manage
        lots: the return of a not yet stored receipt is validated without a
        batch, just like the receipt and quality control transfers it undoes.
        """
        self.ensure_one()
        supplier_location = self.env.ref('stock.stock_location_suppliers')
        return {
            'name': _('Return to Vendor (Not Stored)'),
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
        """Return the not stored return operation, creating it when missing.

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

    def _get_picking_type_update_values(self):
        values = super()._get_picking_type_update_values()
        for picking_type, lot_settings in (
                self._pre_putaway_lot_settings().items()):
            values.setdefault(picking_type, {}).update(lot_settings)
        values['sn_unstored_return_type_id'] = {
            'active': self.reception_steps != 'one_step',
        }
        return values

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
        return values, max_sequence + 1

    def _get_sequence_values(self, name=False, code=False):
        values = super()._get_sequence_values(name=name, code=code)
        name = name if name else self.name
        code = code if code else self.code
        values['sn_unstored_return_type_id'] = {
            'name': _('%(name)s Sequence return to vendor', name=name),
            'prefix': code + '/' + (
                self.sn_unstored_return_type_id.sequence_code or 'RTV') + '/',
            'padding': 5,
            'company_id': self.company_id.id,
        }
        return values
