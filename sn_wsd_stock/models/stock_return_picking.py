from odoo import models


class StockReturnPicking(models.TransientModel):
    _inherit = 'stock.return.picking'

    def _prepare_picking_default_values_based_on(self, picking):
        """Send received goods back to the vendor through a single operation.

        The default return operation of a receipt is the delivery operation,
        which requires an existing lot. With a multi-step reception the goods
        returned from the receipt, the quality control transfer or the storage
        transfer all go through the dedicated vendor return operation instead,
        from the location holding the goods to the vendor. That operation does
        not require a lot, so the goods not stored yet are returned as is,
        while the goods already stored keep their batch from the reservation.
        """
        values = super()._prepare_picking_default_values_based_on(picking)
        return_type = picking._get_unstored_return_picking_type()
        if return_type:
            values.update({
                'picking_type_id': return_type.id,
                'location_dest_id': picking._get_vendor_return_location().id,
            })
        return values
