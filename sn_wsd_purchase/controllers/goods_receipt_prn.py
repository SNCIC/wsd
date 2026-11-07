from odoo import http

from odoo.addons.sn_wsd_prn.controllers.base import SnPrnController

from ..report.goods_receipt_prn import render_goods_receipts


class GoodsReceiptPrn(SnPrnController):

    @http.route('/sn_wsd_purchase/goods_receipt/prn',
                type='http', auth='user', methods=['GET'], csrf=False)
    def goods_receipt_prn(self, picking_id=None, picking_ids=None, **kwargs):
        """ESC/P attachment for the SNERP RAW printer bridge.

        Takes one transfer (`picking_id`) or a selection (`picking_ids`), the
        way the button of the form and the batch button of the list call it.
        """
        pickings = self._sn_prn_records('stock.picking',
                                        picking_ids or picking_id)
        data = render_goods_receipts(pickings)
        return self._sn_prn_response(
            data, self._sn_prn_filename('Purchase-Receipt', pickings))
