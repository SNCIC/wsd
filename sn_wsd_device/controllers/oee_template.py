import io
from datetime import date

import xlsxwriter

from odoo import _, http
from odoo.http import request

from odoo.addons.sn_wsd_device.models.oee_import_wizard import IMPORT_HEADERS


def get_template_headers():
    """Template column headers, translated at call time so the downloaded
    Excel follows the requesting user's language."""
    return [_(english) for _field, english, _zh in IMPORT_HEADERS]


class OeeImportTemplateController(http.Controller):
    """Download the xlsx template used to import OEE records."""

    @http.route('/sn_wsd_device/oee_import_template.xlsx',
                type='http', auth='user')
    def download_oee_import_template(self, **kwargs):
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('OEE')
        header_format = workbook.add_format({'bold': True, 'bg_color': '#D9D9D9'})
        for column, header in enumerate(get_template_headers()):
            sheet.write(0, column, header, header_format)
            sheet.set_column(column, column, 24)
        date_format = workbook.add_format({'num_format': 'yyyy-mm-dd'})
        sheet.write_datetime(1, 1, date(2026, 8, 1), date_format)
        sheet.write(1, 0, 'Example: TEST-EQ-001')
        sheet.write(1, 2, 'all')
        sheet.write(1, 3, '8')
        sheet.write(1, 4, '0.5')
        sheet.write(1, 5, '150')
        sheet.write(1, 6, '1000')
        sheet.write(1, 7, '980')
        workbook.close()
        xlsx_data = output.getvalue()
        return request.make_response(
            xlsx_data,
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-'
                                 'officedocument.spreadsheetml.sheet'),
                ('Content-Disposition',
                 'attachment; filename=oee_import_template.xlsx;'),
            ],
        )
