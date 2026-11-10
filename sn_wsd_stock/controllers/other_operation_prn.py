from odoo import http

from odoo.addons.sn_wsd_prn.controllers.base import SnPrnController

from ..report.other_operation_prn import (
    render_other_deliveries, render_other_receipts)


class OtherOperationPrn(SnPrnController):
    """ESC/P downloads of the other receipt and other delivery sheets."""

    @http.route('/sn_wsd_stock/other_receipt/prn',
                type='http', auth='user', methods=['GET'], csrf=False)
    def other_receipt_prn(self, picking_id=None, picking_ids=None, **kwargs):
        """ESC/P attachment of the other receipts, for the SNERP bridge."""
        pickings = self._sn_prn_records('stock.picking',
                                        picking_ids or picking_id)
        data = render_other_receipts(pickings)
        return self._sn_prn_response(
            data, self._sn_prn_filename('Other-Receipt', pickings))

    @http.route('/sn_wsd_stock/other_delivery/prn',
                type='http', auth='user', methods=['GET'], csrf=False)
    def other_delivery_prn(self, picking_id=None, picking_ids=None, **kwargs):
        """ESC/P attachment of the other deliveries, for the SNERP bridge."""
        pickings = self._sn_prn_records('stock.picking',
                                        picking_ids or picking_id)
        data = render_other_deliveries(pickings)
        return self._sn_prn_response(
            data, self._sn_prn_filename('Other-Delivery', pickings))
