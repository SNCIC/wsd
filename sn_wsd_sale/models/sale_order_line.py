from odoo import fields, models


class SaleOrderLine(models.Model):
    """Expose the columns the order detail report lists on every line."""

    _inherit = 'sale.order.line'

    product_code = fields.Char(
        related='product_id.default_code',
        string='Product Code',
        readonly=True,
    )
    product_name = fields.Char(
        related='product_id.name',
        string='Product Name',
        readonly=True,
    )
    order_date = fields.Datetime(
        related='order_id.date_order',
        string='Order Date',
        readonly=True,
    )
    note = fields.Char(
        string='Note',
        help='Remark written on the line, printed after the amounts.',
    )
