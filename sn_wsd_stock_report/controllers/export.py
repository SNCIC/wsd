import io
import json

import xlsxwriter
from werkzeug.exceptions import BadRequest, Forbidden

from odoo import fields, http
from odoo.http import content_disposition, request
from odoo.tools import osutil

REPORT_MODEL = 'sn.wsd.stock.balance.report'
REPORT_ACTION = 'sn_wsd_stock_report.action_sn_wsd_stock_balance_report'

# Column order of the workbook: label columns first, then the quantities.
# The labels are read from the model fields so the file matches the list view.
LABEL_FIELDS = (
    ('default_code', 20),
    ('product_name', 34),
    ('material_specification', 26),
    ('uom_id', 12),
    ('warehouse_id', 18),
)
QTY_FIELDS = ('qty_initial', 'qty_in', 'qty_out', 'qty_balance')
QTY_WIDTH = 14


def _parse_date(value, default):
    """Return ``value`` as a date, falling back on ``default`` when empty."""
    if not value:
        return default
    try:
        return fields.Date.to_date(value)
    except (TypeError, ValueError):
        raise BadRequest("Invalid date: %s" % value)


def _parse_domain(raw_domain):
    """Decode the search domain sent by the list view.

    The payload only ever holds data (json), it is never evaluated as code, and
    the ORM validates it before building the query.
    """
    if not raw_domain:
        return []
    try:
        domain = json.loads(raw_domain)
    except (TypeError, ValueError):
        raise BadRequest("Invalid domain")
    return domain if isinstance(domain, list) else []


def _label(value):
    """Flatten a many2one read result into its display name."""
    if isinstance(value, (list, tuple)):
        return value[1] if len(value) > 1 else ''
    return value or ''


class StockBalanceExport(http.Controller):
    """Download the stock in/out balance report as an Excel workbook."""

    @http.route('/sn_wsd_stock_report/export/xlsx', type='http', auth='user')
    def export_balance_xlsx(self, date_from=None, date_to=None, domain=None, **kwargs):
        if not request.env.user.has_group('stock.group_stock_user'):
            raise Forbidden()

        range_model = request.env['sn.wsd.stock.balance.range']
        period = range_model._current(request.env)
        date_from = _parse_date(date_from, period.date_from)
        date_to = _parse_date(date_to, period.date_to)
        if date_from > date_to:
            raise BadRequest("The start date must not be later than the end date.")

        # The report view aggregates over the single shared period row, so store
        # the requested period before reading: the file then holds exactly the
        # figures the user saw on screen, whatever happened to that row meanwhile.
        period.write({'date_from': date_from, 'date_to': date_to})
        request.env.flush_all()

        report_model = request.env[REPORT_MODEL]
        report_model.invalidate_model()
        rows = report_model.search_read(
            _parse_domain(domain),
            [name for name, _width in LABEL_FIELDS] + list(QTY_FIELDS),
            order='default_code, warehouse_id',
        )

        action_name = request.env.ref(REPORT_ACTION).name
        xlsx_data = self._render_workbook(report_model, rows, action_name, date_from, date_to)

        filename = osutil.clean_filename(
            "%s %s %s.xlsx" % (action_name, date_from, date_to)
        )
        return request.make_response(
            xlsx_data,
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-'
                                 'officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', content_disposition(filename)),
            ],
        )

    def _render_workbook(self, report_model, rows, title, date_from, date_to):
        """Build the workbook in memory and return its bytes."""
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet(title[:31])

        title_format = workbook.add_format({
            'bold': True, 'font_size': 14, 'align': 'center', 'valign': 'vcenter',
        })
        period_format = workbook.add_format({'align': 'left'})
        header_format = workbook.add_format({
            'bold': True, 'bg_color': '#E9ECEF', 'border': 1,
            'text_wrap': True, 'align': 'center', 'valign': 'vcenter',
        })
        cell_format = workbook.add_format({'border': 1, 'valign': 'vcenter'})
        digits = request.env['decimal.precision'].precision_get('Product Unit')
        number_format = '#,##0' + ('.' + '0' * digits if digits else '')
        qty_format = workbook.add_format({'border': 1, 'num_format': number_format})
        total_format = workbook.add_format({'bold': True, 'border': 1, 'bg_color': '#F8F9FA'})
        total_qty_format = workbook.add_format({
            'bold': True, 'border': 1, 'bg_color': '#F8F9FA', 'num_format': number_format,
        })

        labels = report_model.fields_get(
            [name for name, _width in LABEL_FIELDS] + list(QTY_FIELDS)
        )
        headers = [labels[name]['string'] for name, _width in LABEL_FIELDS]
        headers += [labels[name]['string'] for name in QTY_FIELDS]
        last_col = len(headers) - 1

        sheet.set_row(0, 24)
        sheet.merge_range(0, 0, 0, last_col, title, title_format)
        sheet.merge_range(
            1, 0, 1, last_col,
            "%s: %s ~ %s" % (request.env._('Period'), date_from, date_to),
            period_format,
        )
        header_row = 2
        for col, header in enumerate(headers):
            sheet.write(header_row, col, header, header_format)

        totals = dict.fromkeys(QTY_FIELDS, 0.0)
        row_index = header_row + 1
        for record in rows:
            for col, (name, _width) in enumerate(LABEL_FIELDS):
                sheet.write(row_index, col, _label(record.get(name)), cell_format)
            for offset, name in enumerate(QTY_FIELDS):
                quantity = record.get(name) or 0.0
                totals[name] += quantity
                sheet.write(row_index, len(LABEL_FIELDS) + offset, quantity, qty_format)
            row_index += 1

        sheet.write(row_index, 0, request.env._('Total'), total_format)
        for col in range(1, len(LABEL_FIELDS)):
            sheet.write(row_index, col, '', total_format)
        for offset, name in enumerate(QTY_FIELDS):
            sheet.write(
                row_index, len(LABEL_FIELDS) + offset, totals[name], total_qty_format,
            )

        for col, (_name, width) in enumerate(LABEL_FIELDS):
            sheet.set_column(col, col, width)
        for offset in range(len(QTY_FIELDS)):
            col = len(LABEL_FIELDS) + offset
            sheet.set_column(col, col, QTY_WIDTH)
        sheet.freeze_panes(header_row + 1, 0)

        workbook.close()
        return output.getvalue()
