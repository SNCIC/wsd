from odoo import models


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    def _action_done(self):
        self._msd_check_outgoing_usage()
        result = super()._action_done()
        self._msd_initialize_incoming_lots()
        return result

    def _msd_check_outgoing_usage(self):
        for line in self:
            if (
                line.quantity <= 0
                or not line.lot_id
                or not line.lot_id.is_msd_material
                or line.location_id.usage != 'internal'
                or line.location_dest_id.usage == 'internal'
            ):
                continue
            line.lot_id._msd_validate_for_use()

    def _msd_initialize_incoming_lots(self):
        incoming_lots = self.env['stock.lot']
        for line in self:
            if (
                line.quantity > 0
                and line.lot_id
                and line.lot_id.is_msd_material
                and line.location_dest_id.usage == 'internal'
                and line.location_id.usage == 'supplier'
            ):
                incoming_lots |= line.lot_id
        incoming_lots._msd_initialize_sealed()
