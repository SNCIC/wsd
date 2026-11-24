from odoo import models

# Directions that consume the stock: goods leaving to a customer or entering
# production. Moving goods inside the warehouse, sending them back to the
# vendor, scrapping or counting them stays allowed, so a held batch can be
# moved to a quarantine area or disposed of.
CONSUMING_USAGES = ('customer', 'production')


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    def _action_done(self):
        self._sn_check_quality_hold()
        return super()._action_done()

    def _sn_check_quality_hold(self):
        """Refuse to consume a batch or a material under quality hold.

        The check sits on the move line so it covers every path that books the
        stock: the standard transfers, the barcode flows and the MES receipts.
        """
        for line in self:
            if line.quantity <= 0:
                continue
            if line.location_id.usage != 'internal':
                continue
            if line.location_dest_id.usage not in CONSUMING_USAGES:
                continue
            if line.lot_id:
                line.lot_id._sn_check_usable()
            line.product_id.product_tmpl_id._sn_check_usable()
