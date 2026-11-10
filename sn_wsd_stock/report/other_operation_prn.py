"""ESC/P dot-matrix output of the other receipt and the other delivery.

One 135 mm band of the 241 mm continuous form per sheet, the pitch of the other
warehouse forms. The two sheets share one layout: the type of the operation on
its own line, the department, the date and the document number under it, the item
table with its total row, and the signature line.

The table keeps a fixed number of item rows whatever the transfer carries: the
height of the sheet is the pitch of the paper, so a short receipt has to fill the
form with empty rows instead of closing its table higher up.
"""
from odoo.addons.sn_wsd_prn.escp import (
    BAND_MM_135, CELL_PADDING_MM, HORIZONTAL_DPI, INK, PRINTABLE_MM_135, Sheet,
    date_text, mm, rule, stream)

# Item rows of the sheet. The paper form is pre-printed with six lines; the
# empty ones are drawn so that a transfer of one material keeps the height of
# the form.
ITEM_ROWS = 6

# Bands of the sheet, in millimetres from the top of the form. The printer
# already leaves 6 mm above the form, and the whole sheet has to end above
# PRINTABLE_MM_135.
TITLE_MM = 2
PAGE_MM = 2.5
TYPE_MM = 13.5
TYPE_RULE_MM = 18
META_MM = 20.5
TABLE_TOP_MM = 26.5
HEAD_HEIGHT_MM = 6
ITEM_HEIGHT_MM = 8.5
TOTAL_HEIGHT_MM = 6
SIGNATURE_MM = 97

LOGO_LEFT_MM = 5
LOGO_TOP_MM = 2
LOGO_WIDTH_MM = 42
LOGO_HEIGHT_MM = 11

META_DATE_MM = 95
META_NUMBER_MM = 152
SIGNATURE_COLUMNS_MM = (5, 58, 105, 152)

COLUMNS = (
    (0.06, 'No.'),
    (0.16, 'Material Code'),
    (0.20, 'Material Name'),
    (0.28, 'Specification'),
    (0.06, 'Unit'),
    (0.11, 'Received Quantity'),
    (0.13, 'Remark'),
)
# Column the total quantity lines up with, and the one the total rule keeps.
TOTAL_COLUMN = 5

# Title and operation line of the two sheets.
SHEETS = {
    'other_in': {
        'title': 'Other Receipt Sheet',
        'type_label': 'Receipt Type:',
        'department_field': 'sn_receive_department_id',
        'type_field': 'sn_receive_type_id',
    },
    'other_out': {
        'title': 'Other Delivery Sheet',
        'type_label': 'Business Type:',
        'department_field': 'sn_issue_department_id',
        'type_field': 'sn_issue_type_id',
    },
}


def _draw_band(picking, rows, is_last, page, page_count, kind, translate):
    """Draw one 135 mm band of the sheet on the drawing grid."""
    sheet = Sheet(BAND_MM_135, PRINTABLE_MM_135)
    layout = SHEETS[kind]

    company = picking.company_id
    sheet.logo(LOGO_LEFT_MM, LOGO_TOP_MM, company.logo,
               LOGO_WIDTH_MM, LOGO_HEIGHT_MM)
    sheet.title('%s  %s' % (company.name or '', translate(layout['title'])))
    sheet.draw.text(
        (sheet.right, mm(PAGE_MM)),
        translate('Page %(page)d / %(total)d', page=page, total=page_count),
        font=sheet.small_font, fill=INK, anchor='ra')

    operation_type = picking[layout['type_field']].display_name or ''
    department = picking[layout['department_field']].display_name or ''
    sheet.text(5, TYPE_MM,
               '%s%s' % (translate(layout['type_label']), operation_type))
    # The two head lines are separated like the pre-printed form, so a reader
    # does not take the department for a second type.
    sheet.draw.line([(sheet.left, mm(TYPE_RULE_MM)),
                     (sheet.right, mm(TYPE_RULE_MM))],
                    fill=INK, width=rule(HORIZONTAL_DPI))
    sheet.text(5, META_MM, '%s%s' % (translate('Department:'), department))
    sheet.text(META_DATE_MM, META_MM,
               '%s%s' % (translate('Date:'),
                         date_text(picking, picking.date_done)))
    sheet.text(META_NUMBER_MM, META_MM,
               '%s%s' % (translate('Document No.:'), picking.name or ''))

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
            picking._sn_get_other_operation_prn_total(),
            font=sheet.body_font, fill=INK, anchor='rm')

    sign_y = mm(SIGNATURE_MM)
    for left, label, name in _signature_lines(picking, kind, translate):
        sheet.draw.text((mm(left), sign_y), '%s%s' % (label, name or ''),
                        font=sheet.body_font, fill=INK, anchor='la')

    return sheet.band()


def _signature_lines(picking, kind, translate):
    """Signature columns of the sheet, left to right, as on the paper form.

    The other delivery carries the employee who takes the goods out of the
    stock, the other receipt the one who brings them in; the keeper, the
    inspector and the approver are the same on both.
    """
    approved = (translate('Approved by:'), picking.sn_prn_reviewer_id.name)
    keeper = (translate('Warehouse Keeper:'), picking.sn_prn_keeper_id.name)
    prepared = (translate('Prepared by:'), picking.create_uid.name)
    if kind == 'other_out':
        hand_over = (translate('Collected by:'),
                     picking.sn_issue_employee_id.name)
    else:
        hand_over = (translate('Inspected by:'),
                     picking.sn_prn_inspector_id.name)
    return [
        (SIGNATURE_COLUMNS_MM[0], *approved),
        (SIGNATURE_COLUMNS_MM[1], *hand_over),
        (SIGNATURE_COLUMNS_MM[2], *keeper),
        (SIGNATURE_COLUMNS_MM[3], *prepared),
    ]


def _render(pickings, kind, label):
    """ESC/P bytes of the sheets of `pickings`, one form per band."""
    translate = pickings.env._
    bands = []
    for picking in pickings:
        pages = picking._sn_get_other_operation_prn_pages()
        for page, rows in enumerate(pages, start=1):
            bands.append(_draw_band(
                picking, rows, page == len(pages), page, len(pages), kind,
                translate))
    return stream(bands, PRINTABLE_MM_135, label)


def render_other_receipts(pickings):
    """ESC/P bytes of the other receipt sheets of `pickings`."""
    return _render(pickings, 'other_in', 'other receipt')


def render_other_deliveries(pickings):
    """ESC/P bytes of the other delivery sheets of `pickings`."""
    return _render(pickings, 'other_out', 'other delivery')
