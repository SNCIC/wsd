from odoo import http
from odoo.http import request


class SnLabelPdaController(http.Controller):
    """PDA print channel route (design decision 7): thin shell around the
    service layer so the channel logic stays testable server-side."""

    @http.route('/sn_wsd_label/print_commands', type='jsonrpc', auth='user')
    def print_commands(self, template_id, ids, copies=1):
        return request.env['sn.label.pda.service'].print_commands(
            template_id, ids, copies=copies)
