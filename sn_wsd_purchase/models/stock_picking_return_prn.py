from odoo import models

# Item rows of the sheet: a band of the 135 mm form carries six materials, a
# longer return continues on the next band of the continuous form.
SN_VENDOR_RETURN_ROWS = 6


class StockPicking(models.Model):
    """Data of the dot-matrix purchase return sheet."""

    _inherit = 'stock.picking'

    def _sn_is_vendor_return_prn(self):
        """Whether the transfer sends goods back to a vendor."""
        self.ensure_one()
        return self.sn_prn_vendor_return

    def _sn_get_vendor_return_prn_moves(self):
        """Moves reported on the sheet, in the order of the paper form."""
        self.ensure_one()
        return self.move_ids.filtered(
            lambda move: move.state != 'cancel' and move.product_id
        ).sorted(lambda move: (move.sequence, move.id))

    def _sn_get_vendor_return_prn_lines(self):
        """Rows of the item table, one per returned material."""
        self.ensure_one()
        rows = []
        for index, move in enumerate(self._sn_get_vendor_return_prn_moves(),
                                     start=1):
            quantity = move.quantity or move.product_uom_qty
            price_incl, _rate = self._sn_get_goods_receipt_price(
                move.purchase_line_id)
            if not move.purchase_line_id:
                # A return made without the original purchase order keeps the
                # value the stock carried.
                price_incl = move.product_id.standard_price
            rows.append({
                'sequence': index,
                'product_code': move.product_id.default_code or '',
                'product_name': move.product_id.name or '',
                'material_specification':
                    move.product_id.material_specification or '',
                'uom': move.product_uom.name or '',
                'quantity': self._sn_prn_number(quantity),
                'unit_price': self._sn_prn_number(price_incl, 4),
                'amount': self._sn_prn_number(price_incl * quantity, 2),
                'note': move.description_picking or '',
            })
        return rows

    def _sn_get_vendor_return_prn_pages(self):
        """Split the item rows into the bands of the continuous form."""
        self.ensure_one()
        rows = self._sn_get_vendor_return_prn_lines()
        start = range(0, max(len(rows), 1), SN_VENDOR_RETURN_ROWS)
        return [rows[index:index + SN_VENDOR_RETURN_ROWS] for index in start]

    def _sn_get_vendor_return_prn_totals(self):
        """Quantity and tax included amount of the whole return."""
        self.ensure_one()
        quantity = 0.0
        amount = 0.0
        for move in self._sn_get_vendor_return_prn_moves():
            line_quantity = move.quantity or move.product_uom_qty
            price_incl, _rate = self._sn_get_goods_receipt_price(
                move.purchase_line_id)
            if not move.purchase_line_id:
                price_incl = move.product_id.standard_price
            quantity += line_quantity
            amount += price_incl * line_quantity
        return {
            'quantity': self._sn_prn_number(quantity, 2),
            'amount': self._sn_prn_number(amount, 2),
        }

    def action_print_vendor_return_prn(self):
        """Download the ESC/P stream of the return for the print bridge."""
        return self._sn_prn_action('/sn_wsd_purchase/vendor_return/prn')
