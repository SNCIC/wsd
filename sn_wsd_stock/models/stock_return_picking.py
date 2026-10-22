from odoo import models


class StockReturnPicking(models.TransientModel):
    _inherit = 'stock.return.picking'

    def _prepare_picking_default_values_based_on(self, picking):
        """Send not yet stored goods back without requiring a batch.

        The default return operation of a receipt is the delivery operation,
        which requires an existing lot. For a multi-step reception the goods
        returned from the receipt or from the quality control transfer have no
        batch yet, so the dedicated return operation is used instead. It is an
        outgoing operation without lot management, and it keeps the same
        source location as the transfer it reverses.
        """
        values = super()._prepare_picking_default_values_based_on(picking)
        return_type = picking._get_unstored_return_picking_type()
        if return_type:
            values.update({
                'picking_type_id': return_type.id,
                'location_dest_id': picking.location_id.id,
            })
        return values
