"""ESC/P dot-matrix output of the expense invoice.

The finance form of the vendor bill: one 135 mm band of the 241 mm continuous
form, the paper of the sale order form, so a batch of bills keeps the
perforation. The amount column is the tax included total of the line and the
price column its tax included unit price, the way the account reads them.
"""
from odoo.addons.sn_wsd_prn.escp import (
    BAND_MM_135, PRINTABLE_MM_135, Sheet, stream)

ITEM_ROWS = 6

TITLE_MM = 2
PAGE_MM = 2.5
COUNT_MM = 8
META_MM = 14
TABLE_TOP_MM = 20
HEAD_HEIGHT_MM = 6
ITEM_HEIGHT_MM = 10

META_DATE_MM = 90
META_NUMBER_MM = 150

COLUMNS = (
    (0.14, 'Expense Code'),
    (0.14, 'Expense Name'),
    (0.06, 'Unit'),
    (0.10, 'Quantity'),
    (0.10, 'Unit Price'),
    (0.06, 'Tax %'),
    (0.10, 'Amount'),
    (0.20, 'Remark'),
    (0.10, 'Used By'),
)


def _draw_band(move, rows, page, page_count, print_count, translate):
    """Draw one 135 mm band of the expense invoice."""
    sheet = Sheet(BAND_MM_135, PRINTABLE_MM_135)

    company = move.company_id
    sheet.title('%s  %s' % (company.name or '',
                            translate('Expense Invoice')))
    sheet.page_label(page, page_count, PAGE_MM)
    sheet.text(195, COUNT_MM, '%s %s' % (translate('Printed:'), print_count),
               anchor='ra')

    vendor = move.partner_id.display_name or ''
    invoice_date = (move.invoice_date.strftime('%Y-%m-%d')
                    if move.invoice_date else '')
    sheet.text(5, META_MM, '%s%s' % (translate('Vendor:'), vendor))
    sheet.text(META_DATE_MM, META_MM,
               '%s%s' % (translate('Invoice Date:'), invoice_date))
    sheet.text(META_NUMBER_MM, META_MM,
               '%s%s' % (translate('Bill No.:'), move.name or ''))

    values = [(
        row['product_code'],
        row['product_name'],
        row['uom'],
        row['quantity'],
        row['unit_price'],
        row['tax_rate'],
        row['amount'],
        row['note'],
        row['department'],
    ) for row in rows]
    values += sheet.blank_rows(len(COLUMNS), ITEM_ROWS - len(values))

    columns = tuple((share, translate(label)) for share, label in COLUMNS)
    sheet.table(TABLE_TOP_MM, HEAD_HEIGHT_MM, ITEM_HEIGHT_MM, columns, values)

    return sheet.band()


def render_expense_invoices(moves):
    """ESC/P bytes of the expense invoice sheets of `moves`."""
    translate = moves.env._
    counts = moves._sn_prn_next_print_count()
    bands = []
    for move in moves:
        pages = move._sn_get_expense_invoice_prn_pages()
        for page, rows in enumerate(pages, start=1):
            bands.append(_draw_band(
                move, rows, page, len(pages), counts[move.id], translate))
    return stream(bands, PRINTABLE_MM_135, 'expense invoice')
