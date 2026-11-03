from odoo import fields, models

LINE_SYNC_FIELDS = ('product_id', 'product_qty', 'price_unit', 'discount', 'name')


class PurchaseOrderLine(models.Model):
    """Push the line changes of a purchase order to the sales order of the
    selling company."""

    _inherit = 'purchase.order.line'

    auto_sale_order_line_id = fields.Many2one(
        'sale.order.line',
        string='Source Sales Order Line',
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
