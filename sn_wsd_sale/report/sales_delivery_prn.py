"""ESC/P dot-matrix output of the sales delivery.

One 135 mm band of the 241 mm continuous form per sheet, the pitch of the sale
order form: the delivery leaves with the order and is printed on the same paper.
Seven materials are printed per band; a longer delivery continues on the next
band of the continuous form.
"""
from odoo.addons.sn_wsd_prn.escp import (
    BAND_MM_135, CELL_PADDING_MM, INK, PRINTABLE_MM_135, Sheet, mm, stream)

ITEM_ROWS = 7

TITLE_MM = 2
PAGE_MM = 2.5
META_MM = 16
NOTE_MM = 22.5
TABLE_TOP_MM = 28
HEAD_HEIGHT_MM = 6
ITEM_HEIGHT_MM = 9
TOTAL_HEIGHT_MM = 6
SIGNATURE_MM = 110

LOGO_LEFT_MM = 5
LOGO_TOP_MM = 2
LOGO_WIDTH_MM = 42
LOGO_HEIGHT_MM = 11

META_DATE_MM = 95
META_NUMBER_MM = 155
SIGNATURE_COLUMNS_MM = (5, 55, 110, 160)

COLUMNS = (
    (0.05, 'No.'),
    (0.18, 'Product Code'),
    (0.18, 'Product Name'),
    (0.25, 'Specification'),
    (0.08, 'Unit'),
    (0.10, 'Quantity'),
    (0.16, 'Remark'),
)
TOTAL_QUANTITY_COLUMN = 5


def _draw_band(picking, rows, is_last, page, page_count, translate):
    """Draw one 135 mm band of the delivery on the drawing grid."""
    sheet = Sheet(BAND_MM_135, PRINTABLE_MM_135)

    company = picking.company_id
    sheet.logo(LOGO_LEFT_MM, LOGO_TOP_MM, company.logo,
               LOGO_WIDTH_MM, LOGO_HEIGHT_MM)
    sheet.title('%s  %s' % (company.name or '',
                            translate('Sales Delivery')))
    sheet.page_label(page, page_count, PAGE_MM)

    customer = picking.partner_id.display_name or ''
    delivery_date = (picking.scheduled_date.strftime('%Y-%m-%d')
                     if picking.scheduled_date else '')
    sheet.text(5, META_MM, '%s%s' % (translate('Customer:'), customer))
    sheet.text(META_DATE_MM, META_MM,
               '%s%s' % (translate('Date:'), delivery_date))
    sheet.text(META_NUMBER_MM, META_MM,
               '%s%s' % (translate('Order No.:'), picking.name or ''))
    sheet.text(5, NOTE_MM, '%s%s' % (
        translate('Remark:'), picking._sn_get_sales_delivery_prn_note()))

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

    columns = tuple((share, translate(label)) for share, label in COLUMNS)
    geometry = sheet.table(
        TABLE_TOP_MM, HEAD_HEIGHT_MM, ITEM_HEIGHT_MM, columns, values,
        extra_height_mm=TOTAL_HEIGHT_MM if is_last else 0.0)

    if is_last:
        bounds = geometry['bounds']
        total_y = (geometry['body_bottom'] + geometry['table_bottom']) // 2
        sheet.draw.text((sheet.left + mm(CELL_PADDING_MM), total_y),
                        translate('Total:'), font=sheet.body_font,
                        fill=INK, anchor='lm')
        sheet.draw.text(
            (bounds[TOTAL_QUANTITY_COLUMN + 1] - mm(CELL_PADDING_MM), total_y),
            picking._sn_get_sales_delivery_prn_total(),
            font=sheet.body_font, fill=INK, anchor='rm')

    sign_y = mm(SIGNATURE_MM)
    prepared_left, keeper_left, picker_left, customer_left = (
        mm(value) for value in SIGNATURE_COLUMNS_MM)
    for left, label, name in (
            (prepared_left, 'Prepared by:', picking.create_uid.name),
            (keeper_left, 'Warehouse:', ''),
            (picker_left, 'Picked by:', ''),
            (customer_left, 'Customer:', '')):
        sheet.draw.text((left, sign_y),
                        '%s%s' % (translate(label), name or ''),
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
