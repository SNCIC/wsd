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
    sn_delivery_date = fields.Date(
        string='Delivery Date',
        copy=True,
        help='Date printed in the delivery date column of the dot-matrix '
             'order sheet. Left empty, the order commitment date is printed.',
    )

    def _sn_get_dot_matrix_delivery_date(self):
        """Delivery date of the line as the sheet prints it (YYYY-MM-DD)."""
        self.ensure_one()
        delivery_date = (self.sn_delivery_date
                         or fields.Date.to_date(self.order_id.commitment_date)
                         or fields.Date.to_date(self.order_id.date_order))
        return delivery_date.strftime('%Y-%m-%d') if delivery_date else ''
