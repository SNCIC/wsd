from odoo import api, fields, models

# Item rows of the purchase receipt sheet. One band of the three-part form
# carries five materials; a longer receipt continues on the next part, the same
# way the inspection request of the quality module does.
SN_GOODS_RECEIPT_ROWS = 5


class StockPicking(models.Model):
    """Data of the dot-matrix purchase receipt sheet."""

    _name = 'stock.picking'
    _inherit = ['stock.picking', 'sn.prn.mixin']

    sn_prn_vendor_return = fields.Boolean(
        string='Vendor Return',
        compute='_compute_sn_prn_vendor_return',
        store=True,
        help='The transfer sends goods back to a vendor: it is printed on the '
             'purchase return sheet.',
    )

    @api.depends('picking_type_id', 'location_dest_id')
    def _compute_sn_prn_vendor_return(self):
        for picking in self:
            picking.sn_prn_vendor_return = bool(
                picking.picking_type_id.code == 'outgoing'
                and picking.location_dest_id.usage == 'supplier')

    def _sn_is_goods_receipt_prn(self):
        """Whether the transfer is a purchase receipt of the paper form."""
        self.ensure_one()
        return (self.picking_type_id.code == 'incoming'
                and any(self.move_ids.mapped('purchase_line_id')))

    def _sn_get_goods_receipt_prn_moves(self):
        """Moves reported on the sheet, in the order of the paper form."""
        self.ensure_one()
        return self.move_ids.filtered(
            lambda move: move.state != 'cancel' and move.product_id
        ).sorted(lambda move: (move.sequence, move.id))

    def _sn_get_goods_receipt_prn_lines(self):
        """Rows of the item table, one per received material."""
        self.ensure_one()
        rows = []
        for index, move in enumerate(self._sn_get_goods_receipt_prn_moves(),
                                     start=1):
            quantity = move.quantity or move.product_uom_qty
            price_incl, tax_rate = self._sn_get_goods_receipt_price(
                move.purchase_line_id)
            rows.append({
                'sequence': index,
                'product_code': move.product_id.default_code or '',
                'product_name': move.product_id.name or '',
                'material_specification':
                    move.product_id.material_specification or '',
                'uom': move.product_uom.name or '',
                'quantity': self._sn_prn_number(quantity),
                'unit_price': self._sn_prn_number(price_incl, 4),
                'tax_rate': tax_rate,
                'amount': self._sn_prn_number(price_incl * quantity, 2),
                'warehouse': move.location_dest_id.display_name or '',
                'note': move.description_picking or '',
            })
        return rows

    def _sn_get_goods_receipt_prn_pages(self):
        """Split the item rows into the parts of the continuous form."""
        self.ensure_one()
        rows = self._sn_get_goods_receipt_prn_lines()
        start = range(0, max(len(rows), 1), SN_GOODS_RECEIPT_ROWS)
        return [rows[index:index + SN_GOODS_RECEIPT_ROWS] for index in start]

    def _sn_get_goods_receipt_prn_totals(self):
        """Quantity and tax included amount of the whole receipt."""
        self.ensure_one()
        quantity = 0.0
        amount = 0.0
        for move in self._sn_get_goods_receipt_prn_moves():
            line_quantity = move.quantity or move.product_uom_qty
            price_incl, _rate = self._sn_get_goods_receipt_price(
                move.purchase_line_id)
            quantity += line_quantity
            amount += price_incl * line_quantity
        return {
            'quantity': self._sn_prn_number(quantity, 2),
            'amount': self._sn_prn_number(amount, 2),
        }

    @api.model
    def _sn_get_goods_receipt_price(self, line):
        """Tax included unit price of a purchase line and its tax rate.

        The sheet is a receipt of the receiving warehouse: the amount column is
        the value booked on the stock, tax included, so the price is the tax
        included price of the purchase line.
        """
        if not line:
            return 0.0, ''
        price = line.price_unit
        taxes = line.tax_ids
        price_incl = price
        if taxes:
            currency = line.order_id.currency_id or line.currency_id
            computed = taxes.compute_all(
                price, currency, 1.0, product=line.product_id,
                partner=line.order_id.partner_id)
            price_incl = computed['total_included']
        rate = sum(tax.amount for tax in taxes
                   if tax.amount_type == 'percent')
        return price_incl, self._sn_prn_number(rate) if rate else ''

    def action_print_goods_receipt_prn(self):
        """Download the ESC/P stream of the receipt for the print bridge."""
        return self._sn_prn_action('/sn_wsd_purchase/goods_receipt/prn')
