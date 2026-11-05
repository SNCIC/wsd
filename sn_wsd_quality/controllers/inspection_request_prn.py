from odoo import http
from odoo.http import request

from ..report.inspection_request_prn import render_inspection_request

# The stream is ESC/P, not a document a browser can show: the RAW queue of the
# printer takes the bytes as they are.
PRN_CONTENT_TYPE = 'application/octet-stream'


class InspectionRequestPrn(http.Controller):

    @http.route('/sn_wsd_quality/inspection_request/prn',
                type='http', auth='user', methods=['GET'], csrf=False)
    def inspection_request_prn(self, picking_id=None, **kwargs):
        """ESC/P attachment for the SNERP RAW printer bridge.

        SNERP intercepts the download and sends it unchanged to the selected
        dot-matrix printer queue.
        """
        try:
            picking_id = int(picking_id)
        except (TypeError, ValueError):
            raise request.not_found()
        picking = request.env['stock.picking'].browse(picking_id).exists()
        if not picking:
            raise request.not_found()
        picking.check_access('read')

        data = render_inspection_request(picking)
        filename = 'Inspection-Request-%s.prn' % (
            (picking.name or str(picking.id)).replace('/', '-'))
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
