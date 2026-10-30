"""ESC/P dot-matrix output of the inspection request.

The PDF reports are rasterised by the printer driver at a low resolution, and
the Chinese strokes come out dotted. A dot-matrix printer prints the sheet
better when it receives the dots to put on the paper: the sheet is drawn here
on a 180 dpi grid (the resolution of the printer), thresholded to one bit per
dot and emitted with the ESC * 24-dot double-density command, which every
Epson compatible printer (Deli, Epson LQ, ...) understands.

The desktop client feeds the dot matrix printer through its RAW queue, so
nothing is scaled or resampled again between this file and the paper.
"""
import logging
import os

from PIL import Image, ImageDraw, ImageFont

_logger = logging.getLogger(__name__)

# The printer works at 180 x 180 dpi: one millimetre is 7.09 dots.
DPI = 180
_DOTS = DPI / 25.4

# One part of the three-part continuous form, minus the side margins of the
# printer (about 20 mm of the 241 mm sheet are not printable).
BAND_MM = 93
WIDTH_MM = 200
CONTENT_LEFT_MM = 5
CONTENT_RIGHT_MM = 195

# Rows of the item table, the same as the paper form.
ITEM_ROWS = 5
HEAD_HEIGHT_MM = 5.3
ITEM_HEIGHT_MM = 10.8

FONT_PATHS = (
    '/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    'C:/Windows/Fonts/simsun.ttc',
    'C:/Windows/Fonts/msyh.ttc',
)

# (share of the width, header). The dot matrix sheet is printed for the
# Chinese workshops only: the labels are the ones of the paper form.
COLUMNS = (
    (0.04, '序号'),
    (0.13, '物料编码'),
    (0.15, '物料名称'),
    (0.18, '规格型号'),
    (0.06, '重量'),
    (0.09, '批号'),
    (0.05, '单位'),
    (0.09, '收货数量'),
    (0.09, '收货仓库'),
    (0.12, '采购订单号'),
)


def _font(size):
    for path in FONT_PATHS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:  # pragma: no cover - broken font file
                continue
    _logger.warning('inspection request: no CJK font found, using the default')
    return ImageFont.load_default()


def _mm(value):
    return int(round(value * _DOTS))


def _fit_text(draw, text, font, max_width):
    """Cut the text to the width of its column.

    A dot-matrix sheet has no cell clipping: a long material name would run
    over the next column. The surplus is dropped and marked with two dots.
    """
    text = text or ''
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + '..', font=font) > max_width:
        text = text[:-1]
    return text + '..' if text else ''


def _draw_sheet(picking, lines):
    """Draw the sheet on a one bit canvas of 180 dpi dots."""
    width = _mm(WIDTH_MM)
    height = _mm(BAND_MM)
    image = Image.new('1', (width, height), 1)
    draw = ImageDraw.Draw(image)
    black = 0

    title = _font(44)
    body = _font(22)
    small = _font(18)

    left = _mm(CONTENT_LEFT_MM)
    right = _mm(CONTENT_RIGHT_MM)

    company = picking.company_id.name or ''
    draw.text((width // 2, _mm(7)), '%s  送检单' % company,
              font=title, fill=black, anchor='ma')
    draw.text((right, _mm(9)), '1 / 1', font=small, fill=black, anchor='ra')

    meta_y = _mm(16)
    draw.text((left, meta_y), '供应商：%s' % (picking.partner_id.name or ''),
              font=body, fill=black, anchor='la')
    business_date = (picking.scheduled_date.strftime('%Y-%m-%d')
                     if picking.scheduled_date else '')
    draw.text((_mm(105), meta_y), '业务日期：%s' % business_date,
              font=body, fill=black, anchor='la')
    draw.text((_mm(150), meta_y), '单据编号：%s' % (picking.name or ''),
              font=body, fill=black, anchor='la')

    table_top = _mm(21.5)
    head_bottom = table_top + _mm(HEAD_HEIGHT_MM)
    body_bottom = head_bottom + _mm(ITEM_HEIGHT_MM * ITEM_ROWS)

    columns = [left]
    for share, _name in COLUMNS:
        columns.append(columns[-1] + int(round((right - left) * share)))
    columns[-1] = right

    line = 2
    for x in columns:
        draw.line([(x, table_top), (x, body_bottom)], fill=black, width=line)
    for index in range(ITEM_ROWS + 1):
        y = head_bottom + _mm(ITEM_HEIGHT_MM) * index
        draw.line([(left, y), (right, y)], fill=black, width=line)
    draw.line([(left, table_top), (right, table_top)], fill=black, width=line)

    head_center = (table_top + head_bottom) // 2
    for index, (_share, name) in enumerate(COLUMNS):
        center = (columns[index] + columns[index + 1]) // 2
        cell_width = columns[index + 1] - columns[index] - _mm(1.5)
        draw.text((center, head_center),
                  _fit_text(draw, name, body, cell_width), font=body,
                  fill=black, anchor='mm')

    for row_index, row in enumerate(lines[:ITEM_ROWS]):
        center_y = (head_bottom + _mm(ITEM_HEIGHT_MM) * row_index
                    + _mm(ITEM_HEIGHT_MM) // 2)
        values = (
            str(row['sequence']),
            row['product_code'],
            row['product_name'],
            row['material_specification'],
            row['weight'],
            row['lot_name'],
            row['uom'],
            row['quantity'],
            row['warehouse'],
            row['origin'],
        )
        for index, value in enumerate(values):
            center = (columns[index] + columns[index + 1]) // 2
            cell_width = columns[index + 1] - columns[index] - _mm(1.5)
            draw.text((center, center_y),
                      _fit_text(draw, value or '', body, cell_width),
                      font=body, fill=black, anchor='mm')

    sign_y = _mm(84)
    draw.text((left, sign_y), '仓管签字：', font=body, fill=black, anchor='la')
    draw.text((_mm(55), sign_y), '质检签字：', font=body, fill=black, anchor='la')
    draw.text((_mm(110), sign_y), '制单：%s' % (picking.create_uid.name or ''),
              font=body, fill=black, anchor='la')
    reviewer = picking.sn_inspection_request_reviewer_id.name or ''
    draw.text((_mm(160), sign_y), '审核：%s' % reviewer,
              font=body, fill=black, anchor='la')

    if picking._sn_is_inspection_request_waived(lines):
        draw.rectangle([_mm(92), sign_y - _mm(1), _mm(106), sign_y + _mm(5)],
                       outline=black, width=2)
        draw.text((_mm(99), sign_y + _mm(2)), '免检', font=body,
                  fill=black, anchor='mm')

    return image


def _escp_bytes(image):
    """Encode the one bit sheet with ESC * 24 dot double density bands."""
    width, height = image.size
    pixels = image.load()
    out = bytearray()
    out += b'\x1b@'            # reset the printer
    out += b'\x1b3\x18'        # line spacing: 24/180 inch
    for top in range(0, height, 24):
        data = bytearray()
        for x in range(width):
            group = [0, 0, 0]
            for bit in range(24):
                y = top + bit
                if y < height and pixels[x, y] == 0:
                    group[bit // 8] |= 1 << (7 - bit % 8)
            data += bytes(group)
        out += b'\x1b*' + bytes([33])
        out += len(data).to_bytes(2, 'little')
        out += bytes(data)
        out += b'\r\n'
    out += b'\x0c'             # form feed
    return bytes(out)


def render_inspection_request(picking):
    """ESC/P bytes of the inspection request of a receipt."""
    picking.ensure_one()
    lines = picking._sn_get_inspection_request_lines()
    return _escp_bytes(_draw_sheet(picking, lines))
