"""ESC/P dot-matrix output of the purchase return.

One 135 mm band of the 241 mm continuous form per sheet, the pitch of the sale
order form: the return is printed on the same paper as the order and the
delivery, so a batch of returns keeps the perforation.
"""
from odoo.addons.sn_wsd_prn.escp import (
    BAND_MM_135, CELL_PADDING_MM, INK, PRINTABLE_MM_135, Sheet, mm, stream)

# Item rows of the sheet, as on the paper form.
ITEM_ROWS = 6

TITLE_MM = 2
NUMBER_MM = 3
PAGE_MM = 8.5
META_MM = 16
TABLE_TOP_MM = 22
HEAD_HEIGHT_MM = 6
ITEM_HEIGHT_MM = 10
TOTAL_HEIGHT_MM = 7
SIGNATURE_MM = 102

LOGO_LEFT_MM = 5
LOGO_TOP_MM = 2
LOGO_WIDTH_MM = 42
LOGO_HEIGHT_MM = 11

META_DATE_MM = 90
META_TYPE_MM = 140
META_COUNT_MM = 195
SIGNATURE_COLUMNS_MM = (5, 110)

COLUMNS = (
    (0.15, 'Material Code'),
    (0.17, 'Material Name'),
    (0.20, 'Specification'),
    (0.06, 'Unit'),
    (0.12, 'Returned Qty'),
    (0.12, 'Unit Price'),
    (0.10, 'Amount'),
    (0.08, 'Remark'),
)
# Columns the quantity and the amount of the total row line up with.
TOTAL_QUANTITY_COLUMN = 4
TOTAL_AMOUNT_COLUMN = 6


def _draw_band(picking, rows, is_last, page, page_count, print_count,
               translate):
    """Draw one 135 mm band of the return on the drawing grid."""
    sheet = Sheet(BAND_MM_135, PRINTABLE_MM_135)

    company = picking.company_id
    sheet.logo(LOGO_LEFT_MM, LOGO_TOP_MM, company.logo,
               LOGO_WIDTH_MM, LOGO_HEIGHT_MM)
    sheet.title('%s  %s' % (company.name or '',
                            translate('Purchase Return')))
    sheet.text(META_COUNT_MM, NUMBER_MM, 'NO. %s' % (picking.name or ''),
               anchor='ra')
    sheet.page_label(page, page_count, PAGE_MM)

    vendor = picking.partner_id.display_name or ''
    business_date = (picking.scheduled_date.strftime('%Y-%m-%d')
                     if picking.scheduled_date else '')
    sheet.text(5, META_MM, '%s%s' % (translate('Vendor:'), vendor))
    sheet.text(META_DATE_MM, META_MM,
               '%s%s' % (translate('Date:'), business_date))
    sheet.text(META_TYPE_MM, META_MM,
               '%s%s' % (translate('Document Type:'),
                         picking.picking_type_id.name or ''))
    sheet.text(META_COUNT_MM, META_MM,
               '%s %s' % (translate('Printed:'), print_count), anchor='ra')

    values = [(
        row['product_code'],
        row['product_name'],
        row['material_specification'],
        row['uom'],
        row['quantity'],
        row['unit_price'],
        row['amount'],
        row['note'],
    ) for row in rows]
    values += sheet.blank_rows(len(COLUMNS), ITEM_ROWS - len(values))

    columns = tuple((share, translate(label)) for share, label in COLUMNS)
    geometry = sheet.table(
        TABLE_TOP_MM, HEAD_HEIGHT_MM, ITEM_HEIGHT_MM, columns, values,
        extra_height_mm=TOTAL_HEIGHT_MM if is_last else 0.0)

    if is_last:
        totals = picking._sn_get_vendor_return_prn_totals()
        bounds = geometry['bounds']
        total_y = (geometry['body_bottom'] + geometry['table_bottom']) // 2
        sheet.draw.text((sheet.left + mm(CELL_PADDING_MM), total_y),
                        translate('Total:'), font=sheet.body_font,
                        fill=INK, anchor='lm')
        for column, value in ((TOTAL_QUANTITY_COLUMN, totals['quantity']),
                              (TOTAL_AMOUNT_COLUMN, totals['amount'])):
            sheet.draw.text(
                (bounds[column + 1] - mm(CELL_PADDING_MM), total_y), value,
                font=sheet.body_font, fill=INK, anchor='rm')

    reviewer_left, prepared_left = (mm(value)
                                   for value in SIGNATURE_COLUMNS_MM)
    sign_y = mm(SIGNATURE_MM)
    sheet.draw.text(
        (reviewer_left, sign_y),
        '%s%s' % (translate('Approved by:'),
                  picking.sn_prn_reviewer_id.name or ''),
        font=sheet.body_font, fill=INK, anchor='la')
    sheet.draw.text(
        (prepared_left, sign_y),
        '%s%s' % (translate('Prepared by:'), picking.create_uid.name or ''),
        font=sheet.body_font, fill=INK, anchor='la')

    return sheet.band()


def render_vendor_returns(pickings):
    """ESC/P bytes of the purchase return sheets of `pickings`."""
    translate = pickings.env._
    counts = pickings._sn_prn_next_print_count()
    bands = []
    for picking in pickings:
        pages = picking._sn_get_vendor_return_prn_pages()
        for page, rows in enumerate(pages, start=1):
            bands.append(_draw_band(
                picking, rows, page == len(pages), page, len(pages),
                counts[picking.id], translate))
    return stream(bands, PRINTABLE_MM_135, 'purchase return')
