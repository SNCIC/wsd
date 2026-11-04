from odoo import fields, models
from odoo.tools import formatLang
from odoo.tools.misc import get_lang

# Item rows of the dot-matrix order sheet. The continuous form gives one 140 mm
# band per order; a longer order continues on the next band instead of losing
# its last lines, the same way the inspection request of the quality module
# continues on the next part of its three-part form.
SN_DOT_MATRIX_ROWS = 7


class SaleOrder(models.Model):
    """Fields and data of the dot-matrix order sheet."""

    _inherit = 'sale.order'

    sn_summary = fields.Char(
        string='Summary',
        copy=True,
        help='Line printed under the customer block of the dot-matrix order '
             'sheet, e.g. the subject of the order.',
    )

    # ------------------------------------------------------------------
    # Dot-matrix sheet data
    # ------------------------------------------------------------------
    def _sn_get_dot_matrix_order_lines(self):
        """Order lines reported on the sheet: no section nor note line."""
        self.ensure_one()
        return self.order_line.filtered(
            lambda line: not line.display_type and line.product_uom_qty)

    def _sn_get_dot_matrix_lines(self):
        """Rows of the item table, one per reported order line."""
        self.ensure_one()
        rows = []
        for index, line in enumerate(self._sn_get_dot_matrix_order_lines(),
                                     start=1):
            rows.append({
                'sequence': index,
                'product_code': line.product_code or '',
                'product_name': line.product_name or line.name or '',
                'material_specification': line.material_specification or '',
                'uom': line.product_uom_id.name or '',
                'quantity': self._sn_format_dot_matrix_quantity(
                    line.product_uom_qty),
                'delivery_date': line._sn_get_dot_matrix_delivery_date(),
                'note': line.note or '',
            })
        return rows

    def _sn_get_dot_matrix_pages(self):
        """Split the item rows into the bands of the continuous form.

        A band is a page: the template prints one page per returned list and
        the ESC/P stream feeds one form length per list.
        """
        self.ensure_one()
        rows = self._sn_get_dot_matrix_lines()
        start = range(0, max(len(rows), 1), SN_DOT_MATRIX_ROWS)
        return [rows[index:index + SN_DOT_MATRIX_ROWS] for index in start]

    def _sn_get_dot_matrix_blank_rows(self, rows):
        """Row numbers that keep the item table of a band at its full height."""
        self.ensure_one()
        return range(max(SN_DOT_MATRIX_ROWS - len(rows), 0))

    def _sn_format_dot_matrix_quantity(self, value):
        """Quantity without trailing zeroes, as the paper form shows it."""
        precision = self.env['decimal.precision'].precision_get('Product Unit')
        formatted = formatLang(self.env, value, digits=precision)
        decimal_point = get_lang(self.env).decimal_point or '.'
        if decimal_point not in formatted:
            return formatted
        return formatted.rstrip('0').rstrip(decimal_point)

    def _sn_get_dot_matrix_total(self):
        """Total quantity of the order, printed in the total row of the sheet."""
        self.ensure_one()
        total = sum(self._sn_get_dot_matrix_order_lines().mapped(
            'product_uom_qty'))
        return self._sn_format_dot_matrix_quantity(total)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_sale_order_prn_preview(self):
        """Show the dot-matrix sheet in the browser, before any printing."""
        self.ensure_one()
        return self.env.ref(
            'sn_wsd_sale.action_report_sale_order_prn_preview'
        ).report_action(self, config=False)

    def action_sale_order_prn_pdf(self):
        """Render the dot-matrix sheet as a PDF of the 241 x 140 mm form."""
        self.ensure_one()
        return self.env.ref(
            'sn_wsd_sale.action_report_sale_order_prn'
        ).report_action(self, config=False)

    def action_print_sale_order_prn(self):
        """Download the ESC/P stream of the selection for the print bridge.

        The whole selection goes to the bridge in one file: the sheet of every
        order takes its 140 mm band of the continuous form, so the batch is
        printed in one job.
        """
        return {
            'type': 'ir.actions.act_url',
            'url': '/sn_wsd_sale/sale_order/prn?order_ids=%s' % ','.join(
                str(order_id) for order_id in self.ids),
            'target': 'self',
        }
