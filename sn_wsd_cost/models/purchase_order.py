from odoo import models


class PurchaseOrder(models.Model):
    """Keep the latest purchase price of the products up to date.

    The price is written when an order is confirmed and when one is cancelled:
    a cancellation drops the price read from that order, so the material falls
    back on the previous order of the vendor pricelist instead of keeping a
    price that no longer exists.
    """

    _inherit = 'purchase.order'

    def write(self, vals):
        state_changed = 'state' in vals
        result = super().write(vals)
        if state_changed and vals.get('state') in ('purchase', 'done', 'cancel'):
            self._sn_refresh_order_products_price()
        return result

    def _sn_refresh_order_products_price(self):
        """Refresh the materials ordered on the orders."""
        for order in self:
            products = order.order_line.filtered(
                lambda line: not line.display_type and line.product_id
            ).product_id
            if products:
                products.product_tmpl_id._sn_refresh_latest_purchase_price(
                    order.company_id)
        return True
