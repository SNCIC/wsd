"""ESC/P dot-matrix engine of the printed sheets.

The PDF reports are rasterised by the printer driver at a low resolution and
the Chinese strokes come out dotted. A dot-matrix printer prints a sheet better
when it receives the dots to put on the paper: the sheet is drawn on a 360 dpi
grid, reduced to one bit per printed dot and emitted with the ESC * 24-dot
graphics command in 120 x 180 dpi mode, the graphics density of the installed
LQ-630KII.

Three details decide whether the printer prints the whole sheet:

* a band of the 200 mm width is 4 kB to 8 kB of graphics, more than the line
  buffer of the printer, so each 24-dot line is sent in chunks of 192 dots,
  every one placed with the ESC $ absolute position command;
* the paper is fed by the line spacing set with ESC 3 (24/180 inch) and a
  newline. ESC J is not usable on this printer: its argument 0x18 is the CAN
  control code and cancelled the rest of the job;
* the last line of a band is fed by its remaining dots only, so the paper
  keeps the pitch of the form.

The printer does not use the whole band: measured on the installed LQ-630KII,
it starts about 6 mm below the perforation and stops about 13 mm above the next
one. A sheet is therefore laid out in the top ``printable_mm`` of its band.

Every document module keeps its own layout, in its own ``report/*_prn.py``:
only the drawing primitives, the dithering and the ESC/P commands live here.
"""
import base64
import functools
import io
import logging
import os

from PIL import Image, ImageDraw, ImageFont, ImageOps

from odoo import fields

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

# Width of the paper, minus the side margins of the printer (about 20 mm of the
# 241 mm sheet are not printable).
WIDTH_MM = 200
CONTENT_LEFT_MM = 5
CONTENT_RIGHT_MM = 195

# Bands of the continuous form. The three-part form of the inspection request
# and of the purchase receipt is 93 mm; the sale order form and the sheets laid
# out like it take 135 mm. The band of a sheet is the pitch of the paper: a band
# that feeds more than the form pushes every following sheet lower.
BAND_MM_93 = 93
PRINTABLE_MM_93 = 78
BAND_MM_135 = 135
PRINTABLE_MM_135 = 116

# Font sizes of the drawing grid (360 dpi): 88 dots are a 6.2 mm em.
TITLE_SIZE = 88
BODY_SIZE = 44
SMALL_SIZE = 36

# Table rules: two printed dots. A single dot line is thinner than the dot the
# needle puts on the paper and comes out dotted.
RULE_DOTS = 2

# Columns per ESC * command: 576 bytes of graphics data, well inside the line
# buffer of the printer.
CHUNK_COLUMNS = 192

# Space kept between the border of a cell and its value.
CELL_PADDING_MM = 1.5

PAPER = 255                    # white of a grayscale canvas
INK = 0                        # black of a grayscale canvas
# Share of a printed dot that has to be covered by a drawn stroke to print: the
# strokes are antialiased, and their thin parts would fall out of a threshold
# taken at the middle of the scale (128).
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
def font(size):
    """CJK font of the drawing grid, loaded once per size."""
    for path in FONT_PATHS:
        if not os.path.exists(path):
            continue
        try:
            return ImageFont.truetype(path, size)
        except OSError:  # pragma: no cover - broken font file
            _logger.warning('dot-matrix sheet: unusable font %s', path)
    # The labels and most of the values are Chinese: a fallback font would
    # print them as boxes on a sheet that is signed or handed to a customer.
    raise RuntimeError(
        'dot-matrix sheet: no CJK font found, looked in %s'
        % ', '.join(FONT_PATHS))


def mm(value):
    """Millimetres to dots of the drawing grid."""
    return int(round(value * DRAW_DPI / 25.4))


def rule(dpi=HORIZONTAL_DPI):
    """Width of a table rule in drawing dots, for an output density."""
    return RULE_DOTS * DRAW_DPI // dpi


def clean(value):
    """Single line text of a value: a newline would break the cell anchor."""
    return ' '.join(str(value or '').split())


def date_text(record, value):
    """Date of a sheet as the paper forms write it: 2026/11/6.

    The day is read in the time zone of the user who launches the print job, not
    in UTC: a transfer validated at 7 a.m. in China is one day ahead of the UTC
    date, and the sheet is signed on the day the workshop sees.
    """
    if not value:
        return ''
    value = fields.Datetime.context_timestamp(record, value)
    return '%d/%d/%d' % (value.year, value.month, value.day)


def fit_text(draw, text, text_font, max_width):
    """Cut the text to the width of its column.

    Used by the head row only: a header has to stay on its line, and a dot
    matrix printer has no cell clipping, so the surplus of a long header is
    dropped.
    """
    if draw.textlength(text, font=text_font) <= max_width:
        return text
    while text and draw.textlength(text + '..', font=text_font) > max_width:
        text = text[:-1]
    return text + '..' if text else ''


def wrap_text(draw, text, text_font, max_width, max_lines):
    """Split the value of a cell into the lines the row height gives.

    The values of the item table are wrapped on their characters rather than
    cut: the name of a material is what the reader of the sheet looks for, and
    two short lines keep it whole where one cut line used to lose its tail.
    """
    text = clean(text)
    if not text:
        return []
    lines = []
    current = ''
    for char in text:
        candidate = current + char
        if current and draw.textlength(candidate, font=text_font) > max_width:
            lines.append(current)
            if len(lines) == max_lines:
                return lines
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def draw_cell(draw, text, text_font, center, max_width, max_lines):
    """Draw the value of a cell, wrapped and centred on the cell."""
    lines = wrap_text(draw, text, text_font, max_width, max_lines)
    if not lines:
        return
    step = int(round(text_font.size * 1.2))
    top = center[1] - (len(lines) - 1) * step // 2
    for index, line in enumerate(lines):
        draw.text((center[0], top + index * step),
                  line, font=text_font, fill=INK, anchor='mm')


def column_bounds(left, right, columns):
    """Left edge of every column of the item table, in drawing dots."""
    bounds = [left]
    width = right - left
    for share, _label in columns:
        bounds.append(bounds[-1] + int(round(width * share)))
    bounds[-1] = right
    return bounds


def header_font(draw, column_widths, labels):
    """Largest font the headers fit in, so the head row stays even."""
    for text_font in (font(BODY_SIZE), font(SMALL_SIZE)):
        if all(draw.textlength(label, font=text_font) <= width
               for label, width in zip(labels, column_widths)):
            return text_font
    return font(SMALL_SIZE)


def dot_matrix(image, printable_mm, label='dot-matrix sheet'):
    """Return the printed dots of a band and the height of the band in dots.

    The average of the three by two drawn dots of one printed dot is taken
    before the threshold, so that the antialiasing of the strokes is not thrown
    away dot by dot.
    """
    size = (int(round(image.width * HORIZONTAL_DPI / DRAW_DPI)),
            int(round(image.height * VERTICAL_DPI / DRAW_DPI)))
    image = image.resize(size, Image.Resampling.BOX)
    # ESC * shifts out the set bits, so the ink has to carry them: the sheet is
    # inverted first, the black ink becoming the high values of the scale.
    image = ImageOps.invert(image)
    dots = image.point(
        lambda value: 255 if value >= INK_THRESHOLD else 0, '1')
    height = dots.height
    # A layout that reaches into the last millimetres of the band loses that
    # part of the sheet on paper: the printer skips the bottom of the form.
    box = dots.getbbox()
    printable = int(round(printable_mm * VERTICAL_DPI / 25.4))
    if box and box[3] > printable:
        _logger.warning(
            '%s: the sheet reaches %.1f mm of the %s mm band, the printer '
            'prints %s mm of it', label, box[3] * 25.4 / VERTICAL_DPI,
            image.height * 25.4 / VERTICAL_DPI, printable_mm)
    # ESC * works on whole 24-dot lines: the last one of the band is completed
    # with dots the printer never receives, the paper feed stops above them.
    rows = -(-height // 24) * 24
    if rows != height:
        padded = Image.new('1', (dots.width, rows))  # 0: no dot to print
        padded.paste(dots, (0, 0))
        dots = padded
    return dots, height


def band_bytes(dots, height):
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
            # The form ends between two lines: feed its remaining dots only.
            out += LINE_SPACING + bytes([remaining])
        out += LINE_FEED
    return bytes(out)


def stream(bands, printable_mm, label='dot-matrix sheet'):
    """ESC/P job of `bands`: one form per band, in the order they were drawn."""
    out = bytearray(RESET)
    for image in bands:
        dots, height = dot_matrix(image, printable_mm, label)
        out += band_bytes(dots, height)
    # The printer keeps the line spacing between jobs: hand the default back.
    out += LINE_SPACING_RESET
    out += CARRIAGE_RETURN
    return bytes(out)


class Sheet:
    """One band of the continuous form, drawn on the 360 dpi grid.

    The layout of a document is written with the primitives below: a title, a
    page label, the head line of the document, an item table and the signature
    line. Nothing here knows about a business model, so the same primitives
    serve every sheet.
    """

    def __init__(self, band_mm=BAND_MM_135, printable_mm=PRINTABLE_MM_135,
                 width_mm=WIDTH_MM, content_left_mm=CONTENT_LEFT_MM,
                 content_right_mm=CONTENT_RIGHT_MM):
        self.band_mm = band_mm
        self.printable_mm = printable_mm
        self.width = mm(width_mm)
        self.left = mm(content_left_mm)
        self.right = mm(content_right_mm)
        self.image = Image.new('L', (self.width, mm(band_mm)), PAPER)
        self.draw = ImageDraw.Draw(self.image)
        self.title_font = font(TITLE_SIZE)
        self.body_font = font(BODY_SIZE)
        self.small_font = font(SMALL_SIZE)

    # -- text ------------------------------------------------------------
    def text(self, x_mm, y_mm, value, text_font=None, anchor='la'):
        """Draw a single line of text at a millimetre anchor."""
        self.draw.text((mm(x_mm), mm(y_mm)), clean(value),
                       font=text_font or self.body_font, fill=INK, anchor=anchor)

    def title(self, value, y_mm=1):
        """Centred sheet title, in the title size."""
        self.draw.text((self.width // 2, mm(y_mm)), clean(value),
                       font=self.title_font, fill=INK, anchor='ma')

    def page_label(self, page, page_count, y_mm=2.5):
        """Page count of the sheet, right aligned like the paper forms."""
        self.draw.text((self.right, mm(y_mm)), '%d / %d' % (page, page_count),
                       font=self.small_font, fill=INK, anchor='ra')

    def logo(self, x_mm, y_mm, data, max_width_mm=45, max_height_mm=12):
        """Paste the company logo, scaled inside the given box.

        The logo is a raster image like the rest of the sheet: it is reduced to
        the 360 dpi grid and dithered with the same threshold, so a colour logo
        prints as its grey levels.
        """
        image = load_image(data)
        if not image:
            return
        width = mm(max_width_mm)
        height = mm(max_height_mm)
        scale = min(width / image.width, height / image.height)
        size = (max(1, int(round(image.width * scale))),
                max(1, int(round(image.height * scale))))
        image = image.resize(size, Image.Resampling.LANCZOS)
        self.image.paste(image, (mm(x_mm), mm(y_mm)))

    # -- table -----------------------------------------------------------
    def table_bounds(self, columns):
        """Left edge of every column of the item table."""
        return column_bounds(self.left, self.right, columns)

    def table(self, top_mm, head_height_mm, row_height_mm, columns, rows,
              extra_height_mm=0.0, is_last=True):
        """Draw the item table with its head row, and return its geometry.

        `rows` are lists of cell values, in the order of `columns`; a row
        shorter than the columns is padded with empty cells. `extra_height_mm`
        is the height of the extra bands under the item rows (the total row of
        a sheet), ruled with the same vertical lines.
        """
        bounds = self.table_bounds(columns)
        table_top = mm(top_mm)
        head_bottom = table_top + mm(head_height_mm)
        body_bottom = head_bottom + mm(row_height_mm) * len(rows)
        table_bottom = body_bottom + (mm(extra_height_mm) if extra_height_mm else 0)
        widths = [bounds[index + 1] - bounds[index] - mm(CELL_PADDING_MM)
                  for index in range(len(columns))]

        for index, x in enumerate(bounds):
            # The side borders run the whole table; the inner rules stop under
            # the item rows, so the total rows under them read across the
            # columns as they do on the paper form.
            border = index in (0, len(bounds) - 1)
            bottom = table_bottom if border else body_bottom
            self.draw.line([(x, table_top), (x, bottom)],
                           fill=INK, width=rule(HORIZONTAL_DPI))
        for index in range(len(rows) + 1):
            y = head_bottom + mm(row_height_mm) * index
            self.draw.line([(self.left, y), (self.right, y)],
                           fill=INK, width=rule(VERTICAL_DPI))
        self.draw.line([(self.left, table_top), (self.right, table_top)],
                       fill=INK, width=rule(VERTICAL_DPI))
        if is_last and table_bottom != body_bottom:
            self.draw.line([(self.left, table_bottom),
                            (self.right, table_bottom)],
                           fill=INK, width=rule(VERTICAL_DPI))

        labels = [self._header_label(column) for column in columns]
        head_center = (table_top + head_bottom) // 2
        head_font = header_font(self.draw, widths, labels)
        for index, label in enumerate(labels):
            center = (bounds[index] + bounds[index + 1]) // 2
            self.draw.text(
                (center, head_center),
                fit_text(self.draw, label, head_font, widths[index]),
                font=head_font, fill=INK, anchor='mm')

        # Lines a cell of the item table holds: the row height divided by the
        # spacing of the body font.
        cell_lines = max(1, mm(row_height_mm) // int(round(self.body_font.size * 1.2)))
        for row_index, row in enumerate(rows):
            center_y = (head_bottom + mm(row_height_mm) * row_index
                        + mm(row_height_mm) // 2)
            for column_index, value in enumerate(row[:len(columns)]):
                center = (bounds[column_index] + bounds[column_index + 1]) // 2
                draw_cell(self.draw, value, self.body_font, (center, center_y),
                          widths[column_index], cell_lines)

        return {
            'bounds': bounds,
            'widths': widths,
            'table_top': table_top,
            'head_bottom': head_bottom,
            'body_bottom': body_bottom,
            'table_bottom': table_bottom,
        }

    @staticmethod
    def _header_label(column):
        """Header of a column: a bare label or a (share, label) pair."""
        return column[1] if isinstance(column, (tuple, list)) else column

    def blank_rows(self, row_count, drawn):
        """Empty rows that keep the item table at the height of the form."""
        return [[''] * row_count for _index in range(max(0, drawn))]

    # -- output ----------------------------------------------------------
    def band(self):
        """The drawn band, ready for the ESC/P stream."""
        return self.image


def load_image(data):
    """Decode the raster image of a logo, as the fields store it.

    An image field hands its content over as base64 (bytes or text), so the
    bytes are decoded first; the content that is already a file is kept as is,
    which keeps the helper usable with a logo read from the disk.
    """
    if not data:
        return None
    if isinstance(data, str):
        data = data.encode()
    image = _open_image(data)
    if image is None:
        try:
            image = _open_image(base64.b64decode(data, validate=False))
        except (TypeError, ValueError):
            image = None
    if image is None:
        _logger.warning('dot-matrix sheet: unusable logo')
        return None
    # The sheet is drawn in grey levels: a colour logo keeps them, a
    # transparent one is laid on white.
    if image.mode in ('RGBA', 'LA'):
        background = Image.new('L', image.size, PAPER)
        background.paste(image.convert('L'), mask=image.split()[-1])
        return background
    return image.convert('L')


def _open_image(data):
    """Image content of a byte string, or None when it is not one."""
    try:
        return Image.open(io.BytesIO(data))
    except (OSError, ValueError):
        return None
