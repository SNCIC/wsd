from odoo import http

from odoo.addons.sn_wsd_prn.controllers.base import SnPrnController

from ..report.vendor_return_prn import render_vendor_returns


class VendorReturnPrn(SnPrnController):

    @http.route('/sn_wsd_purchase/vendor_return/prn',
                type='http', auth='user', methods=['GET'], csrf=False)
    def vendor_return_prn(self, picking_id=None, picking_ids=None, **kwargs):
        """ESC/P attachment of the purchase return, for the SNERP bridge."""
        pickings = self._sn_prn_records('stock.picking',
                                        picking_ids or picking_id)
        data = render_vendor_returns(pickings)
        return self._sn_prn_response(
            data, self._sn_prn_filename('Purchase-Return', pickings))
