from odoo import models


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

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

    def _get_picking_type_update_values(self):
        values = super()._get_picking_type_update_values()
        for picking_type, lot_settings in (
                self._pre_putaway_lot_settings().items()):
            values.setdefault(picking_type, {}).update(lot_settings)
        return values

    def _get_picking_type_create_values(self, max_sequence):
        values, max_sequence = super()._get_picking_type_create_values(
            max_sequence)
        for picking_type, lot_settings in (
                self._pre_putaway_lot_settings().items()):
            values.setdefault(picking_type, {}).update(lot_settings)
        return values, max_sequence
