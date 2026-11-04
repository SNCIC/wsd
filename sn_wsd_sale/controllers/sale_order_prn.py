from odoo import http
from odoo.http import request

from ..report.sale_order_prn import render_sale_order

# The stream is ESC/P, not a document a browser can show: the RAW queue of the
# printer takes the bytes as they are.
PRN_CONTENT_TYPE = 'application/octet-stream'


class SaleOrderPrn(http.Controller):

    @http.route('/sn_wsd_sale/sale_order/prn',
                type='http', auth='user', methods=['GET'], csrf=False)
    def sale_order_prn(self, order_id=None, **kwargs):
        """ESC/P attachment for the SNERP RAW printer bridge.

        SNERP intercepts the download and sends it unchanged to the selected
        dot-matrix printer queue.
        """
        try:
            order_id = int(order_id)
        except (TypeError, ValueError):
            raise request.not_found()
        order = request.env['sale.order'].browse(order_id).exists()
        if not order:
            raise request.not_found()
        order.check_access('read')

        data = render_sale_order(order)
        filename = 'Sale-Order-%s.prn' % (
            (order.name or str(order.id)).replace('/', '-'))
        return request.make_response(
            data,
            headers=[
                ('Content-Type', PRN_CONTENT_TYPE),
                ('Content-Disposition',
                 'attachment; filename="%s"' % filename),
                # The bridge hands the length of the buffer to the spooler: a
                # chunked response would be refused by a printer queue.
                ('Content-Length', str(len(data))),
                ('Cache-Control', 'no-store'),
            ])
