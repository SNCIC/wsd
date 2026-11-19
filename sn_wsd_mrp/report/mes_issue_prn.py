"""ESC/P dot-matrix output of the MES material issue sheets.

Two sheets leave the same picking, as on paper: the short one lists the
materials and the quantity delivered, the detailed one adds the product the
material is issued for, the quantity asked for and the code of the material it
replaces. Both are one 135 mm band of the 241 mm continuous form.
"""
from odoo.addons.sn_wsd_prn.escp import (
    BAND_MM_135, CELL_PADDING_MM, INK, PRINTABLE_MM_135, Sheet, mm, stream)

ITEM_ROWS = 6
DETAIL_ITEM_ROWS = 8

TITLE_MM = 2
PAGE_MM = 2.5
META_MM = 16
TABLE_TOP_MM = 22
HEAD_HEIGHT_MM = 6
ITEM_HEIGHT_MM = 9.5
TOTAL_HEIGHT_MM = 6.5
SIGNATURE_MM = 100

DETAIL_META_MM = 14
DETAIL_PRODUCT_MM = 19
DETAIL_TABLE_TOP_MM = 24
DETAIL_ITEM_HEIGHT_MM = 8
DETAIL_SIGNATURE_MM = 102

LOGO_LEFT_MM = 5
LOGO_TOP_MM = 2
LOGO_WIDTH_MM = 42
LOGO_HEIGHT_MM = 11

META_DATE_MM = 90
META_NUMBER_MM = 150
SIGNATURE_COLUMNS_MM = (5, 50, 100, 150)
DETAIL_SIGNATURE_COLUMNS_MM = (5, 70, 140)

DETAIL_META_DATE_MM = 85
DETAIL_META_DEPARTMENT_MM = 145
DETAIL_META_NAME_MM = 70
DETAIL_META_SPECIFICATION_MM = 140

COLUMNS = (
    (0.05, 'No.'),
    (0.18, 'Material Code'),
    (0.20, 'Material Name'),
    (0.35, 'Specification'),
    (0.07, 'Unit'),
    (0.15, 'Issued Qty'),
)
TOTAL_QUANTITY_COLUMN = 5

DETAIL_COLUMNS = (
    (0.05, 'No.'),
    (0.16, 'Material Code'),
    (0.17, 'Material Name'),
    (0.28, 'Specification'),
    (0.06, 'Unit'),
    (0.10, 'Demand Qty'),
    (0.10, 'Issued Qty'),
    (0.08, 'Old Code'),
)


def _draw_band(picking, rows, is_last, page, page_count, translate):
    """Draw one 135 mm band of the material issue sheet."""
    sheet = Sheet(BAND_MM_135, PRINTABLE_MM_135)

    company = picking.company_id
    sheet.logo(LOGO_LEFT_MM, LOGO_TOP_MM, company.logo,
               LOGO_WIDTH_MM, LOGO_HEIGHT_MM)
    sheet.title('%s  %s' % (company.name or '',
                            translate('Production Material Issue')))
    sheet.page_label(page, page_count, PAGE_MM)

    issue_date = (picking.scheduled_date.strftime('%Y-%m-%d')
                  if picking.scheduled_date else '')
    sheet.text(5, META_MM, '%s%s' % (
        translate('Department:'), picking._sn_get_mes_material_department()))
    sheet.text(META_DATE_MM, META_MM,
               '%s%s' % (translate('Date:'), issue_date))
    sheet.text(META_NUMBER_MM, META_MM,
               '%s%s' % (translate('Document No.:'), picking.name or ''))

    values = [(
        row['sequence'],
        row['product_code'],
        row['product_name'],
        row['material_specification'],
        row['uom'],
        row['quantity'],
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
            picking._sn_get_mes_material_prn_total(),
            font=sheet.body_font, fill=INK, anchor='rm')

    sign_y = mm(SIGNATURE_MM)
    for left_mm, label, name in zip(
            SIGNATURE_COLUMNS_MM,
            ('Warehouse Keeper:', 'Received by:', 'Prepared by:',
             'Approved by:'),
            ('', '', picking.create_uid.name or '',
             picking.sn_prn_reviewer_id.name or '')):
        sheet.draw.text((mm(left_mm), sign_y),
                        '%s%s' % (translate(label), name),
                        font=sheet.body_font, fill=INK, anchor='la')

    return sheet.band()


def _draw_detail_band(picking, rows, page, page_count, translate):
    """Draw one 135 mm band of the detailed material issue sheet."""
    sheet = Sheet(BAND_MM_135, PRINTABLE_MM_135)

    company = picking.company_id
    sheet.logo(LOGO_LEFT_MM, LOGO_TOP_MM, company.logo,
               LOGO_WIDTH_MM, LOGO_HEIGHT_MM)
    sheet.title('%s  %s' % (company.name or '',
                            translate('Production Material Issue')))
    sheet.page_label(page, page_count, PAGE_MM)

    issue_date = (picking.scheduled_date.strftime('%Y-%m-%d')
                  if picking.scheduled_date else '')
    sheet.text(5, DETAIL_META_MM, '%s%s' % (
        translate('Source Warehouse:'),
        picking.location_id.display_name or ''))
    sheet.text(DETAIL_META_DATE_MM, DETAIL_META_MM,
               '%s%s' % (translate('Date:'), issue_date))
    sheet.text(DETAIL_META_DEPARTMENT_MM, DETAIL_META_MM,
               '%s%s' % (translate('Department:'),
                         picking._sn_get_mes_material_department()))

    product = picking._sn_get_mes_material_product()
    sheet.text(5, DETAIL_PRODUCT_MM, '%s%s' % (
        translate('Product Code:'), product.default_code or ''))
    sheet.text(DETAIL_META_NAME_MM, DETAIL_PRODUCT_MM, '%s%s' % (
        translate('Product Name:'), product.name or ''))
    sheet.text(DETAIL_META_SPECIFICATION_MM, DETAIL_PRODUCT_MM, '%s%s' % (
        translate('Product Specification:'),
        product.material_specification or ''))

    values = [(
        row['sequence'],
        row['product_code'],
        row['product_name'],
        row['material_specification'],
        row['uom'],
        row['demand_quantity'],
        row['quantity'],
        row['old_code'],
    ) for row in rows]
    values += sheet.blank_rows(len(DETAIL_COLUMNS),
                               DETAIL_ITEM_ROWS - len(values))

    columns = tuple((share, translate(label)) for share, label in DETAIL_COLUMNS)
    sheet.table(
        DETAIL_TABLE_TOP_MM, HEAD_HEIGHT_MM, DETAIL_ITEM_HEIGHT_MM,
        columns, values)

    sign_y = mm(DETAIL_SIGNATURE_MM)
    for left_mm, label, name in zip(
            DETAIL_SIGNATURE_COLUMNS_MM,
            ('Approved by:', 'Prepared by:', 'Received by:'),
            (picking.sn_prn_reviewer_id.name or '',
             picking.create_uid.name or '', '')):
        sheet.draw.text((mm(left_mm), sign_y),
                        '%s%s' % (translate(label), name),
                        font=sheet.body_font, fill=INK, anchor='la')

    return sheet.band()


def render_mes_issues(pickings):
    """ESC/P bytes of the material issue sheets of `pickings`."""
    translate = pickings.env._
    pickings._sn_prn_next_print_count()
    bands = []
    for picking in pickings:
        pages = picking._sn_get_mes_issue_prn_pages()
        for page, rows in enumerate(pages, start=1):
            bands.append(_draw_band(picking, rows, page == len(pages), page,
                                    len(pages), translate))
    return stream(bands, PRINTABLE_MM_135, 'material issue')


def render_mes_issue_details(pickings):
    """ESC/P bytes of the detailed material issue sheets of `pickings`."""
    translate = pickings.env._
    pickings._sn_prn_next_print_count()
    bands = []
    for picking in pickings:
        pages = picking._sn_get_mes_issue_prn_detail_pages()
        for page, rows in enumerate(pages, start=1):
            bands.append(_draw_detail_band(picking, rows, page, len(pages),
                                           translate))
    return stream(bands, PRINTABLE_MM_135, 'material issue detail')
