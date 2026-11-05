from odoo import fields, models

LINE_SYNC_FIELDS = ('product_id', 'product_uom_qty', 'price_unit', 'discount', 'name')


class SaleOrderLine(models.Model):
    """Send the goods of an inter-company sale to the inter-company transit
    location and push the line changes to the purchase order of the buyer."""

    _inherit = 'sale.order.line'

    auto_purchase_order_line_id = fields.Many2one(
        'purchase.order.line',
        string='Source Purchase Order Line',
        copy=False,
        readonly=True,
        index='btree_not_null',
    )

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get('skip_intercompany_sync'):
            return res
        if any(field_name in vals for field_name in LINE_SYNC_FIELDS):
            for line in self:
                line.order_id._sn_push_changes({'order_line': True})
        return res

    def unlink(self):
        orders = self.order_id
        res = super().unlink()
        if not self.env.context.get('skip_intercompany_sync'):
            for order in orders:
                order._sn_push_changes({'order_line': True})
        return res

    def _get_location_final(self):
        partner_company = self.env['res.company']._find_company_from_partner(
            self.order_id.partner_id.id)
        if partner_company \
                and partner_company != self.company_id \
                and self.order_id.partner_id != self.order_id.partner_shipping_id:
            return self.order_id.partner_id.property_stock_customer
        return super()._get_location_final()
