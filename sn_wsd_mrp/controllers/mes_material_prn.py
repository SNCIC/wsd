from odoo import http

from odoo.addons.sn_wsd_prn.controllers.base import SnPrnController

from ..report.mes_issue_prn import render_mes_issue_details, render_mes_issues
from ..report.mes_return_prn import render_mes_returns
from ..report.receipt_prn import render_receipts


class MesMaterialPrn(SnPrnController):
    """ESC/P downloads of the MES material issue and return sheets."""

    @http.route('/sn_wsd_mrp/mes_issue/prn',
                type='http', auth='user', methods=['GET'], csrf=False)
    def mes_issue_prn(self, picking_id=None, picking_ids=None, **kwargs):
        pickings = self._sn_prn_records('stock.picking',
                                        picking_ids or picking_id)
        data = render_mes_issues(pickings)
        return self._sn_prn_response(
            data, self._sn_prn_filename('Material-Issue', pickings))

    @http.route('/sn_wsd_mrp/mes_issue_detail/prn',
                type='http', auth='user', methods=['GET'], csrf=False)
    def mes_issue_detail_prn(self, picking_id=None, picking_ids=None,
                             **kwargs):
        pickings = self._sn_prn_records('stock.picking',
                                        picking_ids or picking_id)
        data = render_mes_issue_details(pickings)
        return self._sn_prn_response(
            data, self._sn_prn_filename('Material-Issue-Detail', pickings))

    @http.route('/sn_wsd_mrp/mes_return/prn',
                type='http', auth='user', methods=['GET'], csrf=False)
    def mes_return_prn(self, picking_id=None, picking_ids=None, **kwargs):
        pickings = self._sn_prn_records('stock.picking',
                                        picking_ids or picking_id)
        data = render_mes_returns(pickings)
        return self._sn_prn_response(
            data, self._sn_prn_filename('Material-Return', pickings))

    @http.route('/sn_wsd_mrp/receipt/prn',
                type='http', auth='user', methods=['GET'], csrf=False)
    def receipt_prn(self, picking_id=None, picking_ids=None, **kwargs):
        """ESC/P attachment of the completion receipts, for the bridge."""
        pickings = self._sn_prn_records('stock.picking',
                                        picking_ids or picking_id)
        data = render_receipts(pickings)
        return self._sn_prn_response(
            data, self._sn_prn_filename('Receipt', pickings))
