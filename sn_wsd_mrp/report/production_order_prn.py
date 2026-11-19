"""ESC/P dot-matrix output of the production order sheet.

One 135 mm band of the 241 mm continuous form per manufacturing order: the task
the workshop receives, with the product, the quantity, the dates and the remark
of the planner. A band is printed for every order of a batch.
"""
from odoo import fields

from odoo.addons.sn_wsd_prn.escp import (
    BAND_MM_135, HORIZONTAL_DPI, INK, PRINTABLE_MM_135, VERTICAL_DPI, Sheet,
    draw_cell, mm, rule, stream)

TITLE_MM = 2
META_MM = 14
TABLE_TOP_MM = 20
HEAD_HEIGHT_MM = 6
ITEM_HEIGHT_MM = 9
NOTE_HEIGHT_MM = 10
SIGNATURE_MM = 62

META_DATE_MM = 90
META_NUMBER_MM = 150
PRINT_DATE_MM = 90
SIGNATURE_COLUMNS_MM = (5, 90, 150)

COLUMNS = (
    (0.18, 'Material Code'),
    (0.16, 'Product Name'),
    (0.24, 'Specification'),
    (0.07, 'Unit'),
    (0.10, 'Quantity'),
    (0.125, 'Start Date'),
    (0.125, 'End Date'),
)


def _draw_band(order, data, translate):
    """Draw the band of one production order."""
    sheet = Sheet(BAND_MM_135, PRINTABLE_MM_135)

    company = order.company_id
    sheet.title('%s  %s' % (company.name or '',
                            translate('Production Order')))

    sheet.text(5, META_MM, '%s%s' % (translate('Workshop:'),
                                     data['workshop']))
    sheet.text(META_DATE_MM, META_MM,
               '%s%s' % (translate('Created on:'), data['date']))
    sheet.text(META_NUMBER_MM, META_MM,
               '%s%s' % (translate('No.:'), data['name']))

    values = [(
        data['product_code'],
        data['product_name'],
        data['material_specification'],
        data['uom'],
        data['quantity'],
        data['date_start'],
        data['date_deadline'],
    )]
    columns = tuple((share, translate(label)) for share, label in COLUMNS)
    geometry = sheet.table(
        TABLE_TOP_MM, HEAD_HEIGHT_MM, ITEM_HEIGHT_MM, columns, values)

    # Remark row under the item table: the planner writes the instructions of
    # the task there, so the row spans the whole width.
    note_top = geometry['table_bottom']
    note_bottom = note_top + mm(NOTE_HEIGHT_MM)
    sheet.draw.rectangle([sheet.left, note_top, sheet.right, note_bottom],
                         outline=INK, width=rule(VERTICAL_DPI))
    label_width = geometry['bounds'][1]
    sheet.draw.line([(label_width, note_top), (label_width, note_bottom)],
                    fill=INK, width=rule(HORIZONTAL_DPI))
    sheet.draw.text((label_width // 2, (note_top + note_bottom) // 2),
                    translate('Remark'), font=sheet.body_font, fill=INK,
                    anchor='mm')

    note_left = label_width + mm(1.5)
    note_lines = max(
        1, mm(NOTE_HEIGHT_MM) // int(round(sheet.body_font.size * 1.2)))
    draw_cell(sheet.draw, data['note'], sheet.body_font,
              ((note_left + sheet.right) // 2, (note_top + note_bottom) // 2),
              sheet.right - note_left - mm(1.5), note_lines)

    sign_y = mm(SIGNATURE_MM)
    released_left, print_date_left, prepared_left = (
        mm(value) for value in SIGNATURE_COLUMNS_MM)
    sheet.draw.text(
        (released_left, sign_y),
        '%s%s' % (translate('Released by:'), data['released_by']),
        font=sheet.body_font, fill=INK, anchor='la')
    sheet.draw.text(
        (print_date_left, sign_y),
        '%s%s' % (translate('Print Date:'), data['print_date']),
        font=sheet.body_font, fill=INK, anchor='la')
    sheet.draw.text(
        (prepared_left, sign_y),
        '%s%s' % (translate('Prepared by:'), data['prepared_by']),
        font=sheet.body_font, fill=INK, anchor='la')

    return sheet.band()


def render_production_orders(orders):
    """ESC/P bytes of the production order sheets of `orders`."""
    translate = orders.env._
    orders._sn_prn_next_print_count()
    # The print date is the moment of the job, in the time zone of the user who
    # launched it, not the creation date of the order.
    print_date = fields.Datetime.context_timestamp(
        orders[:1], fields.Datetime.now()).strftime('%Y-%m-%d %H:%M')
    bands = []
    for order in orders:
        data = order._sn_get_production_order_prn_data()
        data['print_date'] = print_date
        bands.append(_draw_band(order, data, translate))
    return stream(bands, PRINTABLE_MM_135, 'production order')
