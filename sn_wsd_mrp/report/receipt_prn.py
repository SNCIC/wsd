"""ESC/P dot-matrix output of the semi-finished and the finished receipts.

One 135 mm band of the 241 mm continuous form per sheet, the pitch of the other
warehouse forms. Both sheets are printed from the completion receipts of a MES
order and share one layout: the workshop of the production line, the date and
the document number on the head, the item table with its total row, and the
signature line.

The two sheets differ by their title and by the print count: the finished
product sheet shows how many times the document has been printed, the
semi-finished one does not, as on the paper forms. The kind is read from the
transfer, because the two receipts go through the same operation type and carry
the same number prefix.

The table keeps a fixed number of item rows whatever the receipt carries: the
height of the sheet is the pitch of the paper, so a short receipt has to fill the
form with empty rows instead of closing its table higher up.
"""
from odoo.addons.sn_wsd_prn.escp import (
    BAND_MM_135, CELL_PADDING_MM, HORIZONTAL_DPI, INK, PRINTABLE_MM_135, Sheet,
    date_text, mm, rule, stream)

# Item rows of the sheet. The paper form is pre-printed with six lines; the
# empty ones are drawn so that a receipt of one product keeps the height of the
# form.
ITEM_ROWS = 6

# Bands of the sheet, in millimetres from the top of the form. The printer
# already leaves 6 mm above the form, and the whole sheet has to end above
# PRINTABLE_MM_135.
TITLE_MM = 2
NUMBER_MM = 2.5
META_MM = 13
TABLE_TOP_MM = 19
HEAD_HEIGHT_MM = 6
ITEM_HEIGHT_MM = 8.5
TOTAL_HEIGHT_MM = 6
SIGNATURE_MM = 90

LOGO_LEFT_MM = 5
LOGO_TOP_MM = 2
LOGO_WIDTH_MM = 42
LOGO_HEIGHT_MM = 11

META_DATE_MM = 78
META_COUNT_MM = 118
META_PAGE_MM = 195
SIGNATURE_COLUMNS_MM = (5, 52, 100, 150)

COLUMNS = (
    (0.06, 'No.'),
    (0.16, 'Material Code'),
    (0.20, 'Product Name'),
    (0.28, 'Specification'),
    (0.06, 'Unit'),
    (0.11, 'Received Quantity'),
    (0.13, 'Remark'),
)
# Column the total quantity lines up with, and the one the total rule keeps.
TOTAL_COLUMN = 5

# Title of the two sheets, and whether the sheet carries the print count.
SHEETS = {
    'finished': ('Finished Product Receipt Sheet', True),
    'semi_finished': ('Semi-Finished Product Receipt Sheet', False),
}


def _draw_band(picking, rows, is_last, page, page_count, print_count,
               translate):
    """Draw one 135 mm band of the receipt on the drawing grid."""
    sheet = Sheet(BAND_MM_135, PRINTABLE_MM_135)
    title, counted = SHEETS[picking.sn_prn_receipt_kind or 'finished']

    company = picking.company_id
    sheet.logo(LOGO_LEFT_MM, LOGO_TOP_MM, company.logo,
               LOGO_WIDTH_MM, LOGO_HEIGHT_MM)
    sheet.title('%s  %s' % (company.name or '', translate(title)))
    sheet.draw.text((sheet.right, mm(NUMBER_MM)),
                    'NO. %s' % (picking.name or ''),
                    font=sheet.small_font, fill=INK, anchor='ra')

    sheet.text(5, META_MM, '%s%s' % (
        translate('Workshop:'), picking._sn_get_mes_material_department()))
    sheet.text(META_DATE_MM, META_MM,
               '%s%s' % (translate('Date:'),
                         date_text(picking, picking.date_done)))
    if counted:
        sheet.text(META_COUNT_MM, META_MM,
                   '%s %s' % (translate('Printed:'), print_count))
    sheet.draw.text(
        (sheet.right, mm(META_MM)),
        translate('Page %(page)d of %(total)d', page=page, total=page_count),
        font=sheet.small_font, fill=INK, anchor='ra')

    values = [(
        row['sequence'],
        row['product_code'],
        row['product_name'],
        row['material_specification'],
        row['uom'],
        row['quantity'],
        row['note'],
    ) for row in rows]
    values += sheet.blank_rows(len(COLUMNS), ITEM_ROWS - len(values))

    # The headers are messages of this module: they are translated here, in the
    # frame of the module that owns them.
    columns = tuple((share, translate(label)) for share, label in COLUMNS)
    geometry = sheet.table(
        TABLE_TOP_MM, HEAD_HEIGHT_MM, ITEM_HEIGHT_MM, columns, values,
        extra_height_mm=TOTAL_HEIGHT_MM if is_last else 0.0)

    if is_last:
        bounds = geometry['bounds']
        total_y = (geometry['body_bottom'] + geometry['table_bottom']) // 2
        # The total row spans the columns up to the quantity and keeps the rules
        # of the quantity and the remark columns, as on the paper form.
        for column in (TOTAL_COLUMN, TOTAL_COLUMN + 1):
            x = bounds[column]
            sheet.draw.line([(x, geometry['body_bottom']),
                             (x, geometry['table_bottom'])],
                            fill=INK, width=rule(HORIZONTAL_DPI))
        sheet.draw.text((sheet.left + mm(CELL_PADDING_MM), total_y),
                        translate('Total:'), font=sheet.body_font, fill=INK,
                        anchor='lm')
        sheet.draw.text(
            (bounds[TOTAL_COLUMN + 1] - mm(CELL_PADDING_MM), total_y),
            picking._sn_get_receipt_prn_total(),
            font=sheet.body_font, fill=INK, anchor='rm')

    sign_y = mm(SIGNATURE_MM)
    for left, label, name in (
            (SIGNATURE_COLUMNS_MM[0], 'Prepared by:', picking.create_uid.name),
            (SIGNATURE_COLUMNS_MM[1], 'Inspected by:',
             picking.sn_prn_inspector_id.name),
            (SIGNATURE_COLUMNS_MM[2], 'Warehouse Keeper:',
             picking.sn_prn_keeper_id.name),
            (SIGNATURE_COLUMNS_MM[3], 'Approved by:',
             picking.sn_prn_reviewer_id.name)):
        sheet.draw.text((mm(left), sign_y),
                        '%s%s' % (translate(label), name or ''),
                        font=sheet.body_font, fill=INK, anchor='la')

    return sheet.band()


def render_receipts(pickings):
    """ESC/P bytes of the completion receipt sheets of `pickings`."""
    translate = pickings.env._
    counts = pickings._sn_prn_next_print_count()
    bands = []
    for picking in pickings:
        pages = picking._sn_get_receipt_prn_pages()
        for page, rows in enumerate(pages, start=1):
            bands.append(_draw_band(
                picking, rows, page == len(pages), page, len(pages),
                counts[picking.id], translate))
    return stream(bands, PRINTABLE_MM_135, 'completion receipt')
