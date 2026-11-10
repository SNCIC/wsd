"""ESC/P dot-matrix output of the sales delivery.

One 135 mm band of the 241 mm continuous form per sheet, the pitch of the sale
order form: the delivery leaves with the order and is printed on the same paper.
Six materials are printed per band and the table keeps a fixed height whatever
the delivery carries, so a short delivery fills the form with empty rows instead
of closing its table higher up. A longer delivery continues on the next band.

The customer reads the delivery note, not the stock: the sheet carries the
product name, the specification, the unit and the quantity, the terms of the
delivery under the table, and the signature of the customer.
"""
from odoo.addons.sn_wsd_prn.escp import (
    BAND_MM_135, CELL_PADDING_MM, HORIZONTAL_DPI, INK, PRINTABLE_MM_135, Sheet,
    date_text, mm, rule, stream)

# Item rows of the sheet, as on the paper form: one band carries six materials.
ITEM_ROWS = 6

# Bands of the sheet, in millimetres from the top of the form. The printer
# already leaves 6 mm above the form, and the whole sheet has to end above
# PRINTABLE_MM_135.
TITLE_MM = 2
META_MM = 14
NOTE_MM = 20.5
TABLE_TOP_MM = 26
HEAD_HEIGHT_MM = 6
ITEM_HEIGHT_MM = 8.5
TOTAL_HEIGHT_MM = 6
TERMS_MM = 91
TERMS_STEP_MM = 3.4
SIGNATURE_MM = 104

LOGO_LEFT_MM = 5
LOGO_TOP_MM = 2
LOGO_WIDTH_MM = 42
LOGO_HEIGHT_MM = 11

META_DATE_MM = 95
META_NUMBER_MM = 152
SIGNATURE_COLUMNS_MM = (5, 90, 150)

COLUMNS = (
    (0.05, 'No.'),
    (0.30, 'Product Name'),
    (0.32, 'Specification'),
    (0.07, 'Unit'),
    (0.10, 'Quantity'),
    (0.16, 'Remark'),
)
TOTAL_QUANTITY_COLUMN = 4


def _draw_band(picking, rows, is_last, page, page_count, translate):
    """Draw one 135 mm band of the delivery on the drawing grid."""
    sheet = Sheet(BAND_MM_135, PRINTABLE_MM_135)

    company = picking.company_id
    sheet.logo(LOGO_LEFT_MM, LOGO_TOP_MM, company.logo,
               LOGO_WIDTH_MM, LOGO_HEIGHT_MM)
    sheet.title('%s  %s' % (company.name or '',
                            translate('Sales Delivery Note')))

    customer = picking.partner_id.display_name or ''
    sheet.text(5, META_MM, '%s%s' % (translate('Customer:'), customer))
    sheet.text(META_DATE_MM, META_MM,
               '%s%s' % (translate('Business Date:'),
                         date_text(picking, picking.scheduled_date)))
    sheet.text(META_NUMBER_MM, META_MM,
               '%s%s' % (translate('Delivery Note No.:'), picking.name or ''))
    sheet.text(5, NOTE_MM, '%s%s' % (
        translate('Summary:'), picking._sn_get_sales_delivery_prn_summary()))

    values = [(
        row['sequence'],
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
        for column in (TOTAL_QUANTITY_COLUMN, TOTAL_QUANTITY_COLUMN + 1):
            x = bounds[column]
            sheet.draw.line([(x, geometry['body_bottom']),
                             (x, geometry['table_bottom'])],
                            fill=INK, width=rule(HORIZONTAL_DPI))
        sheet.draw.text((sheet.left + mm(CELL_PADDING_MM), total_y),
                        translate('Total:'), font=sheet.body_font, fill=INK,
                        anchor='lm')
        sheet.draw.text(
            (bounds[TOTAL_QUANTITY_COLUMN + 1] - mm(CELL_PADDING_MM), total_y),
            picking._sn_get_sales_delivery_prn_total(),
            font=sheet.body_font, fill=INK, anchor='rm')

        # Terms of the delivery under the table: the customer signs against
        # them, so they belong to the sheet and not to the picking remark.
        for index, term in enumerate(picking._sn_get_sales_delivery_prn_terms()):
            sheet.draw.text(
                (sheet.left, mm(TERMS_MM + index * TERMS_STEP_MM)),
                translate(term), font=sheet.small_font, fill=INK, anchor='la')

    sign_y = mm(SIGNATURE_MM)
    issued_left, page_left, customer_left = (
        mm(value) for value in SIGNATURE_COLUMNS_MM)
    sheet.draw.text((issued_left, sign_y),
                    '%s%s' % (translate('Issued by:'),
                              picking.create_uid.name or ''),
                    font=sheet.body_font, fill=INK, anchor='la')
    sheet.draw.text(
        (page_left, sign_y),
        translate('Page %(page)d of %(total)d', page=page, total=page_count),
        font=sheet.body_font, fill=INK, anchor='la')
    sheet.draw.text((customer_left, sign_y),
                    translate('Customer Signature (Stamp):'),
                    font=sheet.body_font, fill=INK, anchor='la')

    return sheet.band()


def render_sales_deliveries(pickings):
    """ESC/P bytes of the sales delivery sheets of `pickings`."""
    translate = pickings.env._
    bands = []
    for picking in pickings:
        pages = picking._sn_get_sales_delivery_prn_pages()
        for page, rows in enumerate(pages, start=1):
            bands.append(_draw_band(picking, rows, page == len(pages), page,
                                    len(pages), translate))
    return stream(bands, PRINTABLE_MM_135, 'sales delivery')
