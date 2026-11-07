from odoo import http

from odoo.addons.sn_wsd_prn.controllers.base import SnPrnController

from ..report.vendor_bill_prn import render_expense_invoices


class ExpenseInvoicePrn(SnPrnController):

    @http.route('/sn_wsd_account/expense_invoice/prn',
                type='http', auth='user', methods=['GET'], csrf=False)
    def expense_invoice_prn(self, move_id=None, move_ids=None, **kwargs):
        """ESC/P attachment of the expense invoice, for the SNERP bridge."""
        moves = self._sn_prn_records('account.move', move_ids or move_id)
        data = render_expense_invoices(moves)
        return self._sn_prn_response(
            data, self._sn_prn_filename('Expense-Invoice', moves))
