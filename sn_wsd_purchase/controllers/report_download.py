"""Download of the editable Word reports.

``/report/download`` of the web client only knows the PDF and the text
conversions, so the office document of the module is streamed by this route:
the handler registered in ``static/src/js/office_report_handler.js`` posts the
name of the report action and the identifiers of the selected records here.
"""

import json

from werkzeug.exceptions import BadRequest

from odoo import http
from odoo.http import content_disposition, request
from odoo.tools import osutil
from odoo.tools.safe_eval import safe_eval, time

MIMETYPES = {
    'docx': 'application/vnd.openxmlformats-officedocument'
            '.wordprocessingml.document',
}


class SnOfficeReportDownload(http.Controller):
    """Stream the .docx reports of the purchase contracts."""

    @http.route('/sn_wsd_purchase/report/office_download', type='http',
                auth='user', methods=['POST'])
    def office_download(self, data=None, context=None, **kwargs):
        report_name, report_type, res_ids = self._parse_request(data)
        if context:
            # Same context handling as the download route of the web client:
            # the language and the allowed companies of the user must reach the
            # rendering, the labels are translated with them.
            try:
                request.update_context(**json.loads(context))
            except (TypeError, ValueError):
                raise BadRequest("Invalid context")
        reports = request.env['ir.actions.report']
        report = reports._get_report_from_name(report_name)
        if not report or report.report_type != report_type:
            raise BadRequest("Unknown %s report: %s" % (report_type, report_name))
        docs = request.env[report.model].browse(res_ids)
        docs.check_access('read')
        content, extension = reports._render(report_name, res_ids)
        filename = '%s.%s' % (report.name, extension)
        if report.print_report_name and len(docs) == 1:
            filename = '%s.%s' % (
                safe_eval(report.print_report_name, {'object': docs, 'time': time}),
                extension)
        filename = osutil.clean_filename(filename)
        return request.make_response(content, headers=[
            ('Content-Type', MIMETYPES[extension]),
            ('Content-Disposition', content_disposition(filename)),
        ])

    @staticmethod
    def _parse_request(data):
        """Read ``[report_name, report_type, ids]`` out of the posted payload."""
        try:
            payload = json.loads(data or '[]')
        except (TypeError, ValueError):
            raise BadRequest("Invalid report request")
        if not isinstance(payload, list) or len(payload) != 3:
            raise BadRequest("Invalid report request")
        report_name, report_type, res_ids = payload
        if report_type not in MIMETYPES:
            raise BadRequest("Unsupported report type: %s" % report_type)
        identifiers = [int(token) for token in str(res_ids).split(',')
                       if token.strip().isdigit()]
        if not identifiers:
            raise BadRequest("No record to export")
        return report_name, report_type, identifiers
