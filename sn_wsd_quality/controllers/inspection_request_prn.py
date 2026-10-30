from odoo import http
from odoo.http import request

from ..report.inspection_request_prn import render_inspection_request


class InspectionRequestPrn(http.Controller):

    @http.route('/sn_wsd_quality/inspection_request/prn',
                type='http', auth='user', methods=['GET'], csrf=False)
    def inspection_request_prn(self, picking_id, **kwargs):
        """ESC/P file of the inspection request, for the RAW printer queue.

        The desktop client downloads this file and sends it unchanged to the
        dot matrix printer: the sheet is already a 180 dpi bitmap, so the
        printer driver has nothing left to rasterise.
        """
        picking = request.env['stock.picking'].browse(int(picking_id))
        picking.check_access_rights('read')
        if not picking.exists():
            raise request.not_found()
        data = render_inspection_request(picking)
        filename = 'Inspection-Request-%s.prn' % (
            (picking.name or str(picking.id)).replace('/', '-'))
        return request.make_response(
            data,
            headers=[
                ('Content-Type', 'application/octet-stream'),
                ('Content-Disposition',
                 'attachment; filename="%s"' % filename),
                ('Cache-Control', 'no-store'),
            ])
