from odoo import http

from odoo.addons.sn_wsd_prn.controllers.base import SnPrnController

from ..report.sales_delivery_prn import render_sales_deliveries


class SalesDeliveryPrn(SnPrnController):

    @http.route('/sn_wsd_sale/sales_delivery/prn',
                type='http', auth='user', methods=['GET'], csrf=False)
    def sales_delivery_prn(self, picking_id=None, picking_ids=None, **kwargs):
        """ESC/P attachment of the delivery, for the SNERP bridge."""
        pickings = self._sn_prn_records('stock.picking',
                                        picking_ids or picking_id)
        data = render_sales_deliveries(pickings)
        return self._sn_prn_response(
            data, self._sn_prn_filename('Sales-Delivery', pickings))
