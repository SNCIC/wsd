from odoo import api, fields, models

# Item rows of the delivery sheet: a band of the 135 mm form carries six
# materials, a longer delivery continues on the next band. The terms of the
# delivery sit under the table, which is what keeps the count at six.
SN_SALES_DELIVERY_ROWS = 6

# Terms printed under the item table of the delivery note. They are the terms
# the customer signs against, so they are kept here rather than on the company:
# a customer receives the same terms whatever the warehouse it is served from.
SN_SALES_DELIVERY_TERMS = (
    'Please inspect the goods within 3 days of the delivery, then sign and '
    'stamp this sheet and send it back to us.',
    'The goods are taken as accepted when this sheet is not sent back within '
    '3 days of the delivery. Damage caused by the transport has to be '
    'reported to us within 7 days of the delivery.',
    'We answer such a claim within 3 days. Beyond that delay we carry no risk '
    'of the transport.',
)


class StockPicking(models.Model):
    """Data of the dot-matrix sales delivery sheet."""

    _name = 'stock.picking'
    _inherit = ['stock.picking', 'sn.prn.mixin']

    sn_prn_sales_delivery = fields.Boolean(
        string='Sales Delivery',
        compute='_compute_sn_prn_sales_delivery',
        store=True,
        help='The transfer delivers the goods of a sale order: it is printed '
             'on the sales delivery sheet.',
    )

    @api.depends('picking_type_id', 'sale_id')
    def _compute_sn_prn_sales_delivery(self):
        for picking in self:
            picking.sn_prn_sales_delivery = bool(
                picking.picking_type_id.code == 'outgoing' and picking.sale_id)

    def _sn_get_sales_delivery_prn_moves(self):
        """Moves reported on the sheet, in the order of the paper form."""
        self.ensure_one()
        return self.move_ids.filtered(
            lambda move: move.state != 'cancel' and move.product_id
        ).sorted(lambda move: (move.sequence, move.id))

    def _sn_get_sales_delivery_prn_lines(self):
        """Rows of the item table, one per delivered material."""
        self.ensure_one()
        rows = []
        for index, move in enumerate(self._sn_get_sales_delivery_prn_moves(),
                                     start=1):
            sale_line = move.sale_line_id
            quantity = move.quantity or move.product_uom_qty
            rows.append({
                'sequence': index,
                'product_code': (sale_line.product_code
                                 or move.product_id.default_code or ''),
                'product_name': (sale_line.product_name
                                 or move.product_id.name or ''),
                'material_specification':
                    move.product_id.material_specification or '',
                'uom': move.product_uom.name or '',
                'quantity': self._sn_prn_number(quantity),
                'note': (sale_line.note if sale_line else '') or '',
            })
        return rows

    def _sn_get_sales_delivery_prn_pages(self):
        """Split the item rows into the bands of the continuous form."""
        self.ensure_one()
        rows = self._sn_get_sales_delivery_prn_lines()
        start = range(0, max(len(rows), 1), SN_SALES_DELIVERY_ROWS)
        return [rows[index:index + SN_SALES_DELIVERY_ROWS] for index in start]

    def _sn_get_sales_delivery_prn_total(self):
        """Total quantity of the delivery, printed in the total row."""
        self.ensure_one()
        total = sum(self._sn_get_sales_delivery_prn_moves().mapped('quantity'))
        return self._sn_prn_number(total, 4)

    def _sn_get_sales_delivery_prn_note(self):
        """Remark of the delivery head, the device test report line of the form."""
        self.ensure_one()
        return self.sn_prn_note or self.note or ''

    def _sn_get_sales_delivery_prn_summary(self):
        """Summary line of the head, read from the sale order of the delivery."""
        self.ensure_one()
        return self.sale_id.sn_summary or ''

    def _sn_get_sales_delivery_prn_terms(self):
        """Terms printed under the item table, one entry per line."""
        self.ensure_one()
        return SN_SALES_DELIVERY_TERMS

    def action_print_sales_delivery_prn(self):
        """Download the ESC/P stream of the delivery for the print bridge."""
        return self._sn_prn_action('/sn_wsd_sale/sales_delivery/prn')
