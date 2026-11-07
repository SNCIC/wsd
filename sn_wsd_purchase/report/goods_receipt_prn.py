"""ESC/P dot-matrix output of the purchase receipt.

The sheet is one 93 mm part of the three-part continuous form, the band of the
inspection request of the quality module: the receipt and the inspection request
travel with the same goods, so the two sheets are printed on the same paper and
keep the same pitch. Five materials are printed per part; a longer receipt
continues on the next one.

The columns and the amount column follow the paper form: the value of a line is
the tax included value booked on the stock.
"""
from odoo.addons.sn_wsd_prn.escp import (
    BAND_MM_93, CELL_PADDING_MM, INK, PRINTABLE_MM_93, Sheet, mm, stream)

# Item rows of the sheet, as on the paper form.
ITEM_ROWS = 5

# Bands of the sheet, in millimetres from the top of the part. The template
# keeps no top margin of its own: the printer already leaves 6 mm, and the whole
# sheet has to end above PRINTABLE_MM_93.
TITLE_MM = 1
NUMBER_MM = 3
PAGE_MM = 7.5
META_MM = 12
TABLE_TOP_MM = 17
HEAD_HEIGHT_MM = 5.5
ITEM_HEIGHT_MM = 8.5
TOTAL_HEIGHT_MM = 5.5
SIGNATURE_MM = 74

META_DATE_MM = 85
META_TYPE_MM = 130
META_COUNT_MM = 195
SIGNATURE_COLUMNS_MM = (5, 110)

# Columns of the item table: share of the width, header. The headers are
# translated with the language of the user, so the sheet follows the interface.
COLUMNS = (
    (0.04, 'No.'),
    (0.12, 'Product Code'),
    (0.12, 'Product Name'),
    (0.18, 'Specification'),
    (0.05, 'Unit'),
    (0.09, 'Quantity'),
    (0.08, 'Unit Price'),
    (0.05, 'Tax %'),
    (0.09, 'Amount'),
    (0.09, 'Warehouse'),
    (0.09, 'Remark'),
)
# Columns the quantity and the amount of the total row line up with.
TOTAL_QUANTITY_COLUMN = 5
TOTAL_AMOUNT_COLUMN = 8


def _draw_band(picking, rows, is_last, page, page_count, print_count,
               translate):
    """Draw one 93 mm part of the receipt on the drawing grid."""
    sheet = Sheet(BAND_MM_93, PRINTABLE_MM_93)

    company = picking.company_id
    sheet.title('%s  %s' % (company.name or '',
                            translate('Purchase Receipt')))
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
        row['sequence'],
        row['product_code'],
        row['product_name'],
        row['material_specification'],
        row['uom'],
        row['quantity'],
        row['unit_price'],
        row['tax_rate'],
        row['amount'],
        row['warehouse'],
        row['note'],
    ) for row in rows]
    values += sheet.blank_rows(len(COLUMNS), ITEM_ROWS - len(values))

    # The headers are messages of this module: they are translated here, in the
    # frame of the module that owns them, so that the term is looked up in its
    # own glossary.
    columns = tuple((share, translate(label)) for share, label in COLUMNS)
    geometry = sheet.table(
        TABLE_TOP_MM, HEAD_HEIGHT_MM, ITEM_HEIGHT_MM, columns, values,
        extra_height_mm=TOTAL_HEIGHT_MM if is_last else 0.0)

    if is_last:
        totals = picking._sn_get_goods_receipt_prn_totals()
        bounds = geometry['bounds']
        total_y = (geometry['body_bottom'] + geometry['table_bottom']) // 2
        sheet.draw.text((sheet.left + mm(CELL_PADDING_MM), total_y),
                        translate('Total:'), font=sheet.body_font, fill=INK,
                        anchor='lm')
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


def render_goods_receipts(pickings):
    """ESC/P bytes of the purchase receipt sheets of `pickings`."""
    translate = pickings.env._
    counts = pickings._sn_prn_next_print_count()
    bands = []
    for picking in pickings:
        pages = picking._sn_get_goods_receipt_prn_pages()
        for page, rows in enumerate(pages, start=1):
            bands.append(_draw_band(
                picking, rows, page == len(pages), page, len(pages),
                counts[picking.id], translate))
    return stream(bands, PRINTABLE_MM_93, 'purchase receipt')
