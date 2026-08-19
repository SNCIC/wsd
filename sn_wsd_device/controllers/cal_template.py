import io

import xlsxwriter

from odoo import _, http
from odoo.http import request


def get_template_headers():
    """Template column headers, translated at call time so the downloaded
    Excel follows the requesting user's language."""
    return [
        _('Item Name'),
        _('Before Calibration Value'),
        _('After Calibration Value'),
        _('Line Note'),
    ]


class CalibrationTemplateController(http.Controller):
    """Download the xlsx template used to fill calibration task lines."""

    @http.route('/sn_wsd_device/calibration_line_template.xlsx',
                type='http', auth='user')
    def download_calibration_template(self, **kwargs):
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('calibration')
        header_format = workbook.add_format({'bold': True, 'bg_color': '#D9D9D9'})
        for column, header in enumerate(get_template_headers()):
            sheet.write(0, column, header, header_format)
            sheet.set_column(column, column, 24)
        sheet.write(1, 0, 'Example: voltage measurement')
        sheet.write(1, 1, '220.1')
        sheet.write(1, 2, '220.0')
        sheet.write(1, 3, '')
        workbook.close()
        xlsx_data = output.getvalue()
        return request.make_response(
            xlsx_data,
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-'
                                 'officedocument.spreadsheetml.sheet'),
                ('Content-Disposition',
                 'attachment; filename=calibration_lines_template.xlsx;'),
            ],
        )
