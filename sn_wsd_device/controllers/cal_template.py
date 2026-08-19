import io

import xlsxwriter

from odoo import http
from odoo.http import request

# Columns of the import template, shared by the download controller and
# the import wizard.
TEMPLATE_HEADERS = ['项目名称', '校准前检测值', '校准后检测值', '单项备注']


class CalibrationTemplateController(http.Controller):
    """Download the xlsx template used to fill calibration task lines."""

    @http.route('/sn_wsd_device/calibration_line_template.xlsx',
                type='http', auth='user')
    def download_calibration_template(self, **kwargs):
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('calibration')
        header_format = workbook.add_format({'bold': True, 'bg_color': '#D9D9D9'})
        for column, header in enumerate(TEMPLATE_HEADERS):
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
