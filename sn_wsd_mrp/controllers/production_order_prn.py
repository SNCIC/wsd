from odoo import http

from odoo.addons.sn_wsd_prn.controllers.base import SnPrnController

from ..report.production_order_prn import render_production_orders


class ProductionOrderPrn(SnPrnController):

    @http.route('/sn_wsd_mrp/production_order/prn',
                type='http', auth='user', methods=['GET'], csrf=False)
    def production_order_prn(self, production_id=None, production_ids=None,
                             **kwargs):
        orders = self._sn_prn_records('mrp.production',
                                      production_ids or production_id)
        data = render_production_orders(orders)
        return self._sn_prn_response(
            data, self._sn_prn_filename('Production-Order', orders))
