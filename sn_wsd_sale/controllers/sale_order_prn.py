from odoo import http
from odoo.http import request

from ..report.sale_order_prn import render_sale_orders

# The stream is ESC/P, not a document a browser can show: the RAW queue of the
# printer takes the bytes as they are.
PRN_CONTENT_TYPE = 'application/octet-stream'

# Orders of one print job. A sheet is about 120 kB of graphics data, and the
# bridge hands the buffer to the spooler as a whole: the batch stays in a size
# a print queue takes without complaint.
MAX_ORDERS = 50


class SaleOrderPrn(http.Controller):

    @http.route('/sn_wsd_sale/sale_order/prn',
                type='http', auth='user', methods=['GET'], csrf=False)
    def sale_order_prn(self, order_id=None, order_ids=None, **kwargs):
        """ESC/P attachment for the SNERP RAW printer bridge.

        Takes one order (`order_id`) or a selection (`order_ids`), the way the
        button of the form and the batch button of the list call it. SNERP
        intercepts the download and sends it unchanged to the selected
        dot-matrix printer queue.
        """
        try:
            order_ids = [int(value) for value in
                         str(order_ids or order_id or '').split(',')
                         if value.strip()]
        except (TypeError, ValueError):
            raise request.not_found()
        if not order_ids:
            raise request.not_found()
        if len(order_ids) > MAX_ORDERS:
            return request.make_response(
                'Too many orders in one print job: %s at most.' % MAX_ORDERS,
                status=400,
                headers=[('Content-Type', 'text/plain; charset=utf-8')])

        orders = request.env['sale.order'].browse(order_ids).exists()
        if len(orders) != len(order_ids):
            raise request.not_found()
        orders.check_access('read')

        data = render_sale_orders(orders)
        if len(orders) == 1:
            name = (orders.name or str(orders.id)).replace('/', '-')
        else:
            name = '%s-%s' % (len(orders), orders[0].name or orders[0].id)
        filename = 'Sale-Order-%s.prn' % name.replace('/', '-')
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
