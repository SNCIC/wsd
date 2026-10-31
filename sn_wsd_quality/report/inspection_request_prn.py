"""ESC/P dot-matrix output of the inspection request.

The PDF reports are rasterised by the printer driver at a low resolution, and
the Chinese strokes come out dotted. A dot-matrix printer prints the sheet
better when it receives the dots to put on the paper: the sheet is drawn here,
reduced to one bit per dot and emitted with the ESC * 24-dot graphics command
in 120 x 180 dpi mode, the graphics density of the installed LQ-630KII.

Three details decide whether the printer prints the whole sheet:

* a 93 mm band of the 200 mm width is 4.2 kB of graphics, more than the line
  buffer of the printer, so each 24-dot line is sent in chunks of 192 dots,
  every one placed with the ESC $ absolute position command;
* the paper is fed by the line spacing set with ESC 3 (24/180 inch) and a
  newline. ESC J is not usable on this printer: its argument 0x18 is the CAN
  control code and cancelled the rest of the job;
* the last line of a band is fed by its remaining dots only, so the paper
  keeps the 93 mm pitch of the three-part continuous form.

The printer does not use the whole part: measured on the installed LQ-630KII,
it starts about 6 mm below the perforation and stops about 13 mm above the
next one. The sheet is therefore laid out in the top PRINTABLE_MM of the band,
which is what keeps the signature line on the paper.

SNERP hands these bytes to the printer; the Windows queue must accept RAW
data (the Epson ESC/P class driver of this printer drops it).
"""
import functools
import logging
import os

from PIL import Image, ImageDraw, ImageFont, ImageOps

_logger = logging.getLogger(__name__)

# Graphics density of the printer: 120 dots per inch horizontally, 180
# vertically. The sheet is drawn at 360 dpi, so three drawn dots reduce to one
# printed dot horizontally and two vertically: the reduction is exact and the
# antialiasing of the strokes survives it.
HORIZONTAL_DPI = 120
VERTICAL_DPI = 180
DRAW_DPI = 360

# ESC/P commands, named after the ESC/P reference of the 24-pin printers.
RESET = b'\x1b@'               # clear the buffer and reset the modes
LINE_FEED = b'\n'              # print the line and feed the paper
CARRIAGE_RETURN = b'\r'        # back to the left margin, no paper feed
LINE_SPACING = b'\x1b3'        # set the line spacing, in 1/180 inch
LINE_SPACING_24_DOTS = b'\x1b3\x18'   # one 24-dot graphics line
LINE_SPACING_RESET = b'\x1b2'  # back to 1/6 inch, the ESC/P default
ABSOLUTE_POSITION = b'\x1b$'   # print position, in 1/60 inch
GRAPHICS_24_DOT = b'\x1b*!'    # ESC * mode 33: 24-dot graphics, 120 x 180 dpi

# One part of the three-part continuous form, minus the side margins of the
# printer (about 20 mm of the 241 mm sheet are not printable).
BAND_MM = 93
WIDTH_MM = 200
CONTENT_LEFT_MM = 5
CONTENT_RIGHT_MM = 195

# The printer does not print every one of the 93 mm of a part: it starts about
# 6 mm below the perforation and stops about 13 mm above the next one, so the
# sheet is drawn in the top PRINTABLE_MM of the band and the rest stays blank.
# The band itself is still fed as 93 mm, the pitch of the form.
PRINTABLE_MM = 78

# Bands of the sheet, in millimetres from the top of the part. The template
# keeps no top margin of its own: the printer already leaves 6 mm, and the
# whole sheet has to end above PRINTABLE_MM.
TITLE_MM = 1
PAGE_MM = 2.5
META_MM = 10
TABLE_TOP_MM = 15
HEAD_HEIGHT_MM = 5
ITEM_HEIGHT_MM = 10.2
SIGNATURE_MM = 72.5
CELL_PADDING_MM = 1.5
META_DATE_MM = 105
META_NUMBER_MM = 150
SIGNATURE_COLUMNS_MM = (5, 55, 110, 160)
WAIVER_BOX_MM = (92, 106)

# Rows of the item table, as on the paper form: one band carries five, a
# longer transfer is printed on the next parts of the continuous form.
ITEM_ROWS = 5

# Font sizes of the drawing grid (360 dpi): 88 dots are a 6.2 mm em.
TITLE_SIZE = 88
BODY_SIZE = 44
SMALL_SIZE = 36
# Table rules: two printed dots. A single dot line is thinner than the dot the
# needle puts on the paper and comes out dotted, the same reason the PDF
# report draws its rules in points instead of pixels.
RULE_DOTS = 2

# Columns of the item table: share of the width, header. The dot matrix sheet
# is printed for the Chinese workshops only: the labels are the ones of the
# paper form.
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

# Columns per ESC * command: 576 bytes of graphics data, well inside the line
# buffer of the printer.
CHUNK_COLUMNS = 192

PAPER = 255                    # white of a grayscale canvas
INK = 0                        # black of a grayscale canvas
# Share of a printed dot that has to be covered by a drawn stroke to print:
# the strokes are antialiased, and their thin parts would fall out of a
# threshold taken at the middle of the scale (128).
INK_THRESHOLD = 100

FONT_PATHS = (
    '/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf',
    '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
    '/usr/share/fonts/truetype/arphic/uming.ttc',
    'C:/Windows/Fonts/simsun.ttc',
    'C:/Windows/Fonts/simhei.ttf',
    'C:/Windows/Fonts/msyh.ttc',
)


@functools.lru_cache(maxsize=None)
def _font(size):
    """CJK font of the drawing grid, loaded once per size."""
    for path in FONT_PATHS:
        if not os.path.exists(path):
            continue
        try:
            return ImageFont.truetype(path, size)
        except OSError:  # pragma: no cover - broken font file
            _logger.warning('inspection request: unusable font %s', path)
    # The labels and most of the values are Chinese: a fallback font would
    # print them as boxes on a sheet that the warehouse signs.
    raise RuntimeError(
        'inspection request: no CJK font found, looked in %s'
        % ', '.join(FONT_PATHS))


def _mm(value):
    """Millimetres to dots of the drawing grid."""
    return int(round(value * DRAW_DPI / 25.4))


def _rule(dpi):
    """Width of a table rule in drawing dots, for an output density."""
    return RULE_DOTS * DRAW_DPI // dpi


def _clean(value):
    """Single line text of a value: a newline would break the cell anchor."""
    return ' '.join(str(value or '').split())


def _fit_text(draw, text, font, max_width):
    """Cut the text to the width of its column.

    A dot-matrix sheet has no cell clipping: a long material name would run
    over the next column. The surplus is dropped and marked with two dots.
    """
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + '..', font=font) > max_width:
        text = text[:-1]
    return text + '..' if text else ''


def _column_bounds(left, right):
    """Left edge of every column of the item table, in drawing dots."""
    bounds = [left]
    for share, _name in COLUMNS:
        bounds.append(bounds[-1] + int(round((right - left) * share)))
    bounds[-1] = right
    return bounds


def _header_font(draw, column_widths):
    """Largest font the ten headers fit in, so the head row stays even."""
    for font in (_font(BODY_SIZE), _font(SMALL_SIZE)):
        if all(draw.textlength(name, font=font) <= width
               for (_share, name), width in zip(COLUMNS, column_widths)):
            return font
    return _font(SMALL_SIZE)


def _draw_sheet(picking, lines, page, page_count, waived):
    """Draw one 93 mm band of the sheet on the drawing grid."""
    width = _mm(WIDTH_MM)
    image = Image.new('L', (width, _mm(BAND_MM)), PAPER)
    draw = ImageDraw.Draw(image)

    title = _font(TITLE_SIZE)
    body = _font(BODY_SIZE)
    small = _font(SMALL_SIZE)

    left = _mm(CONTENT_LEFT_MM)
    right = _mm(CONTENT_RIGHT_MM)

    company = _clean(picking.company_id.name)
    draw.text((width // 2, _mm(TITLE_MM)), '%s  送检单' % company,
              font=title, fill=INK, anchor='ma')
    draw.text((right, _mm(PAGE_MM)), '%d / %d' % (page, page_count),
              font=small, fill=INK, anchor='ra')

    meta_y = _mm(META_MM)
    draw.text((left, meta_y), '供应商：%s' % _clean(picking.partner_id.name),
              font=body, fill=INK, anchor='la')
    business_date = (picking.scheduled_date.strftime('%Y-%m-%d')
                     if picking.scheduled_date else '')
    draw.text((_mm(META_DATE_MM), meta_y), '业务日期：%s' % business_date,
              font=body, fill=INK, anchor='la')
    draw.text((_mm(META_NUMBER_MM), meta_y), '单据编号：%s' % _clean(picking.name),
              font=body, fill=INK, anchor='la')

    table_top = _mm(TABLE_TOP_MM)
    head_bottom = table_top + _mm(HEAD_HEIGHT_MM)
    body_bottom = head_bottom + _mm(ITEM_HEIGHT_MM) * ITEM_ROWS

    columns = _column_bounds(left, right)
    column_widths = [columns[index + 1] - columns[index] - _mm(CELL_PADDING_MM)
                     for index in range(len(COLUMNS))]

    for x in columns:
        draw.line([(x, table_top), (x, body_bottom)],
                  fill=INK, width=_rule(HORIZONTAL_DPI))
    for index in range(ITEM_ROWS + 1):
        y = head_bottom + _mm(ITEM_HEIGHT_MM) * index
        draw.line([(left, y), (right, y)],
                  fill=INK, width=_rule(VERTICAL_DPI))
    draw.line([(left, table_top), (right, table_top)],
              fill=INK, width=_rule(VERTICAL_DPI))

    head_center = (table_top + head_bottom) // 2
    head_font = _header_font(draw, column_widths)
    for index, (_share, name) in enumerate(COLUMNS):
        center = (columns[index] + columns[index + 1]) // 2
        draw.text((center, head_center),
                  _fit_text(draw, name, head_font, column_widths[index]),
                  font=head_font, fill=INK, anchor='mm')

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
            draw.text((center, center_y),
                      _fit_text(draw, _clean(value), body, column_widths[index]),
                      font=body, fill=INK, anchor='mm')

    sign_y = _mm(SIGNATURE_MM)
    signature_left, inspector_left, prepared_left, reviewer_left = (
        _mm(value) for value in SIGNATURE_COLUMNS_MM)
    draw.text((signature_left, sign_y), '仓管签字：',
              font=body, fill=INK, anchor='la')
    draw.text((inspector_left, sign_y), '质检签字：',
              font=body, fill=INK, anchor='la')
    draw.text((prepared_left, sign_y),
              '制单：%s' % _clean(picking.create_uid.name),
              font=body, fill=INK, anchor='la')
    reviewer = _clean(picking.sn_inspection_request_reviewer_id.name)
    draw.text((reviewer_left, sign_y), '审核：%s' % reviewer,
              font=body, fill=INK, anchor='la')

    if waived:
        box_left, box_right = (_mm(value) for value in WAIVER_BOX_MM)
        draw.rectangle([box_left, sign_y - _mm(1), box_right, sign_y + _mm(5)],
                       outline=INK, width=_rule(VERTICAL_DPI))
        draw.text(((box_left + box_right) // 2, sign_y + _mm(2)), '免检',
                  font=body, fill=INK, anchor='mm')

    return image


def _dot_matrix(image):
    """Return the printed dots of a band and the height of the band in dots.

    The average of the three by two drawn dots of one printed dot is taken
    before the threshold, so that the antialiasing of the strokes is not
    thrown away dot by dot.
    """
    size = (int(round(image.width * HORIZONTAL_DPI / DRAW_DPI)),
            int(round(image.height * VERTICAL_DPI / DRAW_DPI)))
    image = image.resize(size, Image.Resampling.BOX)
    # ESC * shifts out the set bits, so the ink has to carry them: the sheet
    # is inverted first, the black ink becoming the high values of the scale.
    image = ImageOps.invert(image)
    dots = image.point(
        lambda value: 255 if value >= INK_THRESHOLD else 0, '1')
    height = dots.height
    # A layout that reaches into the last millimetres of the part loses that
    # part of the sheet on paper: the printer skips the bottom of the form.
    box = dots.getbbox()
    printable = int(round(PRINTABLE_MM * VERTICAL_DPI / 25.4))
    if box and box[3] > printable:
        _logger.warning(
            'inspection request: the sheet reaches %.1f mm of the %s mm part, '
            'the printer prints %s mm of it',
            box[3] * 25.4 / VERTICAL_DPI, BAND_MM, PRINTABLE_MM)
    # ESC * works on whole 24-dot lines: the last one of the band is completed
    # with dots the printer never receives, the paper feed stops above them.
    rows = -(-height // 24) * 24
    if rows != height:
        padded = Image.new('1', (dots.width, rows))  # 0: no dot to print
        padded.paste(dots, (0, 0))
        dots = padded
    return dots, height


def _band_bytes(dots, height):
    """ESC/P graphics of one band of `height` dots, fed 24 dots at a time."""
    width = dots.width
    # One row of the transposed image holds the print columns of one band: its
    # 24 dots are the three bytes of an ESC * column, top dot first, and PIL
    # packs them in that order. Packing with PIL instead of walking the 22 000
    # dots of a line in Python keeps a band in the millisecond range.
    transposed = dots.transpose(Image.Transpose.TRANSPOSE)
    out = bytearray(LINE_SPACING_24_DOTS)
    for top in range(0, height, 24):
        out += CARRIAGE_RETURN
        data = transposed.crop((top, 0, top + 24, width)).tobytes()
        for start in range(0, width, CHUNK_COLUMNS):
            end = min(start + CHUNK_COLUMNS, width)
            # ESC $ counts in 1/60 inch: a 120 dpi dot is half a unit.
            position = start * 60 // HORIZONTAL_DPI
            out += ABSOLUTE_POSITION + position.to_bytes(2, 'little')
            out += GRAPHICS_24_DOT + (end - start).to_bytes(2, 'little')
            out += data[start * 3:end * 3]
        remaining = min(24, height - top)
        if remaining < 24:
            # The part ends between two lines: feed its remaining dots only.
            out += LINE_SPACING + bytes([remaining])
        out += LINE_FEED
    return bytes(out)


def render_inspection_request(picking):
    """ESC/P bytes of the inspection request of a receipt."""
    picking.ensure_one()
    lines = picking._sn_get_inspection_request_lines()
    waived = picking._sn_is_inspection_request_waived(lines)
    # One band per five materials: the form is a continuous form, so a longer
    # transfer continues on the next part instead of losing its last rows.
    pages = [lines[start:start + ITEM_ROWS]
             for start in range(0, max(len(lines), 1), ITEM_ROWS)]
    out = bytearray(RESET)
    for page, page_lines in enumerate(pages, start=1):
        dots, height = _dot_matrix(
            _draw_sheet(picking, page_lines, page, len(pages), waived))
        out += _band_bytes(dots, height)
    # The printer keeps the line spacing between jobs: hand the default back.
    out += LINE_SPACING_RESET
    out += CARRIAGE_RETURN
    return bytes(out)
