from odoo import api, fields, models

# Item rows of the expense invoice: a band of the 135 mm form carries six
# expense lines, a longer invoice continues on the next band.
SN_EXPENSE_INVOICE_ROWS = 6


class AccountMove(models.Model):
    """Data of the dot-matrix expense invoice sheet."""

    _name = 'account.move'
    _inherit = ['account.move', 'sn.prn.mixin']

    sn_prn_is_expense_invoice = fields.Boolean(
        string='Expense Invoice',
        compute='_compute_sn_prn_is_expense_invoice',
        help='The bill is a vendor invoice printed on the expense sheet.',
    )

    @api.depends('move_type')
    def _compute_sn_prn_is_expense_invoice(self):
        for move in self:
            move.sn_prn_is_expense_invoice = move.move_type in (
                'in_invoice', 'in_refund')

    def _sn_get_expense_invoice_prn_lines(self):
        """Rows of the item table: the expense lines of the bill."""
        self.ensure_one()
        rows = []
        index = 0
        for line in self.invoice_line_ids.filtered(
                lambda line: line.display_type == 'product' and line.product_id):
            index += 1
            quantity = line.quantity or 1.0
            amount = line.price_total
            rows.append({
                'sequence': index,
                'product_code': line.product_id.default_code or '',
                'product_name': line.product_id.name or '',
                'uom': line.product_uom_id.name or '',
                'quantity': self._sn_prn_number(line.quantity),
                # The sheet shows the tax included price: the column is read
                # against the amount, which is the tax included total.
                'unit_price': self._sn_prn_number(amount / quantity, 2),
                'tax_rate': self._sn_get_expense_invoice_tax_rate(line),
                'amount': self._sn_prn_number(amount, 2),
                'note': ' '.join((line.name or '').split()),
                'department': line.sn_prn_department_id.display_name or '',
            })
        return rows

    @api.model
    def _sn_get_expense_invoice_tax_rate(self, line):
        """Tax rate of a line, as one figure of the rate column."""
        rate = sum(tax.amount for tax in line.tax_ids
                   if tax.amount_type == 'percent')
        return self._sn_prn_number(rate) if rate else ''

    def _sn_get_expense_invoice_prn_pages(self):
        """Split the expense lines into the bands of the continuous form."""
        self.ensure_one()
        rows = self._sn_get_expense_invoice_prn_lines()
        start = range(0, max(len(rows), 1), SN_EXPENSE_INVOICE_ROWS)
        return [rows[index:index + SN_EXPENSE_INVOICE_ROWS] for index in start]

    def action_print_expense_invoice_prn(self):
        """Download the ESC/P stream of the expense invoice sheet."""
        return self._sn_prn_action('/sn_wsd_account/expense_invoice/prn')
