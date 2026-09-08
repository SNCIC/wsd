import base64
import binascii
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import qrcode

from odoo import _, models
from odoo.exceptions import UserError

DEFAULT_THICKNESS = 2
CPCL_CONTRACT_TAGS = (
    'INIT', 'PAGE-WIDTH', 'TEXT', 'BOX', 'LINE', 'QRCODE', 'BITMAP',
    'BARCODE', 'PRINT',
)
# CPCL built-in ASCII font 7 is a 24-dot high bitmap font: the JSON "bold"
# field of printer_sdk.js acts as its size multiplier.
CPCL_ASCII_FONT = 7
CPCL_ASCII_BASE_HEIGHT = 24


class SnLabelRenderer(models.AbstractModel):
    """Label rendering engine: one layout, three dialects (design decision 3).

    Layout contract (a plain dict so batch-2 template records serialize into
    it and unit tests can run without the ORM models)::

        {
            'width': 560, 'height': 320, 'dpi': 203,
            'elements': [
                {'type': 'box', 'x': 8, 'y': 8, 'width': 544, 'height': 304,
                 'thickness': 2},
                {'type': 'line', 'x': 8, 'y': 60, 'width': 544, 'height': 0,
                 'thickness': 2},          # height 0 = horizontal, width 0 = vertical
                {'type': 'text', 'x': 20, 'y': 20, 'width': 200, 'height': 40,
                 'font_size': 30, 'max_lines': 1, 'align': 'left',
                 'text': 'Fixed title'},    # or 'field_path': 'template_id.code'
                {'type': 'qrcode', 'x': 400, 'y': 170, 'width': 140, 'height': 140,
                 'rendering': 'native',    # or 'bitmap'
                 'field_path': 'sn'},
                {'type': 'barcode', 'x': 20, 'y': 250, 'width': 300, 'height': 60,
                 'text': 'ABC-123'},
            ],
        }

    Dialect rules (fixed in the engine, templates are unaware):
    - boxes / lines: native commands (^GB / BOX, LINE) or PIL drawing
    - QR codes: native (^BQ / QRCODE) unless element rendering == 'bitmap'
    - non-ASCII text (Chinese): always a server-side NotoSansSC bitmap
      (^GFA / BITMAP base64 PNG / preview paste) so all three outputs share
      the very same raster
    - pure-ASCII text: native printer font (^A0 / TEXT font 7)
    """

    _name = 'sn.label.renderer'
    _description = 'Label Rendering Engine'

    # ------------------------------------------------------------------
    # Shared raster primitives (migrated from sn_wsd_stock label report)
    # ------------------------------------------------------------------
    @staticmethod
    def _clean_text(value):
        text = str(value or '').replace('^', ' ').replace('~', ' ')
        return ' '.join(text.split())

    @staticmethod
    def _font_path():
        font_path = Path(__file__).resolve().parent.parent / 'static' / 'fonts' / 'NotoSansSC-VF.ttf'
        return font_path if font_path.exists() else Path('C:/Windows/Fonts/msyh.ttc')

    @classmethod
    def _split_text_lines(cls, text, font, max_width, max_lines):
        lines = []
        current = ''
        for char in text:
            candidate = current + char
            if current and font.getlength(candidate) > max_width:
                lines.append(current)
                current = char
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines if len(lines) <= max_lines else None

    @classmethod
    def _render_text_image(cls, value, font_size, max_width, max_lines=1):
        """Server-side text raster shared by ^GFA, CPCL BITMAP and preview."""
        text = cls._clean_text(value)
        if not text:
            return None
        min_font_size = 16 if max_lines > 1 else 20
        lines = None
        while font_size >= min_font_size:
            font = ImageFont.truetype(str(cls._font_path()), font_size)
            lines = cls._split_text_lines(text, font, max_width, max_lines)
            if lines:
                break
            font_size -= 2
        if not lines:
            font = ImageFont.truetype(str(cls._font_path()), min_font_size)
            lines = cls._split_text_lines(text, font, max_width, max_lines) or [text]

        boxes = [font.getbbox(line) for line in lines]
        text_width = max(1, max(box[2] - box[0] for box in boxes))
        line_height = max(1, max(box[3] - box[1] for box in boxes))
        line_spacing = 4 if len(lines) > 1 else 0
        text_height = line_height * len(lines) + line_spacing * (len(lines) - 1)
        image = Image.new('1', (text_width + 4, text_height + 4), 1)
        draw = ImageDraw.Draw(image)
        for index, line in enumerate(lines):
            box = boxes[index]
            draw.text(
                (2 - box[0], 2 + index * (line_height + line_spacing) - box[1]),
                line,
                font=font,
                fill=0,
                stroke_width=1,
                stroke_fill=0,
            )
        return image

    @staticmethod
    def _image_gfa(image):
        row_bytes = (image.width + 7) // 8
        padded_width = row_bytes * 8
        if padded_width != image.width:
            padded = Image.new('1', (padded_width, image.height), 1)
            padded.paste(image, (0, 0))
            image = padded
        bitmap = bytearray()
        pixels = image.load()
        for y in range(image.height):
            for byte_index in range(row_bytes):
                byte = 0
                for bit_index in range(8):
                    if not pixels[byte_index * 8 + bit_index, y]:
                        byte |= 1 << (7 - bit_index)
                bitmap.append(byte)
        hex_data = binascii.hexlify(bitmap).decode('ascii').upper()
        total_bytes = len(bitmap)
        return f'^GFA,{total_bytes},{total_bytes},{row_bytes},{hex_data}^FS'

    @classmethod
    def _render_qr_image(cls, value, size):
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=1,
            border=2,
        )
        qr.add_data(cls._clean_text(value))
        qr.make(fit=True)
        qr_image = qr.make_image(fill_color='black', back_color='white').convert('1')
        return qr_image.resize((size, size), Image.Resampling.NEAREST)

    @classmethod
    def _qr_module_count(cls, value):
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=1,
            border=0,
        )
        qr.add_data(cls._clean_text(value))
        qr.make(fit=True)
        return len(qr.get_matrix())

    @staticmethod
    def _image_base64_png(image):
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')

    # ------------------------------------------------------------------
    # Intermediate representation
    # ------------------------------------------------------------------
    def _build_ir(self, layout, record):
        """Layout dict + record -> flat drawing ops (box/line/text/qr/barcode)."""
        self._check_layout(layout)
        ops = []
        for element in layout.get('elements', []):
            etype = element.get('type')
            if etype in ('box', 'line'):
                ops.append(self._ir_shape(element))
            elif etype in ('text', 'qrcode', 'barcode'):
                value = self._element_value(element, record)
                if not value:
                    continue
                ops.append(self._ir_mark(etype, element, value))
            else:
                raise UserError(_('Unknown label element type: %s', etype))
        return ops

    def _check_layout(self, layout):
        width = layout.get('width')
        height = layout.get('height')
        if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
            raise UserError(_('The label template width and height must be positive integers.'))

    @staticmethod
    def _ir_shape(element):
        thickness = element.get('thickness') or DEFAULT_THICKNESS
        if element.get('type') == 'box':
            return {'op': 'box', 'x': element['x'], 'y': element['y'],
                    'w': element['width'], 'h': element['height'], 't': thickness}
        return {'op': 'line', 'x1': element['x'], 'y1': element['y'],
                'x2': element['x'] + element['width'],
                'y2': element['y'] + element['height'], 't': thickness}

    @staticmethod
    def _ir_mark(etype, element, value):
        if etype == 'text':
            return {'op': 'text', 'value': value, 'x': element['x'], 'y': element['y'],
                    'w': element['width'], 'h': element['height'],
                    'font_size': element.get('font_size') or 30,
                    'max_lines': element.get('max_lines') or 1,
                    'align': element.get('align') or 'left'}
        if etype == 'qrcode':
            return {'op': 'qr', 'value': value, 'x': element['x'], 'y': element['y'],
                    'size': min(element['width'], element['height']),
                    'bitmap': element.get('rendering') == 'bitmap'}
        return {'op': 'barcode', 'value': value, 'x': element['x'], 'y': element['y'],
                'w': element['width'], 'h': element['height']}

    def _element_value(self, element, record):
        if element.get('text') is not None:
            return self._clean_text(element['text'])
        field_path = element.get('field_path')
        if not field_path:
            return ''
        return self._clean_text(
            self.env['sn.label.reader'].read_value(record, field_path))

    # ------------------------------------------------------------------
    # Placement helpers (alignment + vertical centering, shared dialects)
    # ------------------------------------------------------------------
    def _text_placement(self, op, image):
        """Where to paste a raster of `image` for a text op (top-left corner)."""
        align = op.get('align', 'left')
        offset_x = {'left': 0, 'center': (op['w'] - image.width) // 2,
                    'right': op['w'] - image.width}.get(align, 0)
        x = op['x'] + max(0, offset_x)
        y = op['y'] + max(0, (op['h'] - image.height) // 2)
        return x, y

    def _ascii_lines(self, op):
        """Measured ASCII lines for native-font placement (preview parity)."""
        font = ImageFont.truetype(str(self._font_path()), op['font_size'])
        lines = self._split_text_lines(op['value'], font, op['w'], op['max_lines'])
        if not lines:
            lines = [op['value']]
        boxes = [font.getbbox(line) for line in lines]
        line_height = max(1, max(box[3] - box[1] for box in boxes))
        widths = [font.getlength(line) for line in lines]
        return lines, widths, line_height

    # ------------------------------------------------------------------
    # ZPL dialect
    # ------------------------------------------------------------------
    def render_zpl(self, layout, records, copies=1):
        self.env['sn.label.reader'].check_records(records)
        chunks = []
        for record in records:
            parts = ['^XA', f"^PW{layout['width']}", f"^LL{layout['height']}",
                     '^LH0,0', '^CI28']
            for op in self._build_ir(layout, record):
                parts.append(self._zpl_op(op))
            if copies and copies > 1:
                parts.append(f'^PQ{copies}')
            parts.append('^XZ')
            chunks.append('\n'.join(parts))
        return '\n'.join(chunks)

    def _zpl_op(self, op):
        kind = op['op']
        if kind == 'box':
            return f"^FO{op['x']},{op['y']}^GB{op['w']},{op['h']},{op['t']}^FS"
        if kind == 'line':
            if op['y1'] == op['y2']:
                length = max(1, abs(op['x2'] - op['x1']))
                return f"^FO{min(op['x1'], op['x2'])},{op['y1']}^GB{length},{op['t']},{op['t']}^FS"
            length = max(1, abs(op['y2'] - op['y1']))
            return f"^FO{op['x1']},{min(op['y1'], op['y2'])}^GB{op['t']},{length},{op['t']}^FS"
        if kind == 'qr':
            return self._zpl_qr(op)
        if kind == 'text':
            return self._zpl_text(op)
        return self._zpl_barcode(op)

    def _zpl_qr(self, op):
        if op['bitmap']:
            image = self._render_qr_image(op['value'], op['size'])
            return f"^FO{op['x']},{op['y']}{self._image_gfa(image)}"
        modules = self._qr_module_count(op['value'])
        unit = max(1, min(10, op['size'] // modules))
        side = unit * modules
        offset = max(0, (op['size'] - side) // 2)
        x = op['x'] + offset
        y = op['y'] + offset
        return f"^FO{x},{y}^BQN,2,{unit}^FDMA,{op['value']}^FS"

    def _zpl_text(self, op):
        if op['value'].isascii():
            lines, widths, line_height = self._ascii_lines(op)
            total_height = line_height * len(lines)
            y = op['y'] + max(0, (op['h'] - total_height) // 2)
            commands = []
            for index, line in enumerate(lines):
                align = op.get('align', 'left')
                offset_x = {'left': 0, 'center': (op['w'] - widths[index]) / 2,
                            'right': op['w'] - widths[index]}.get(align, 0)
                x = int(op['x'] + max(0, offset_x))
                commands.append(
                    f"^FO{x},{y + index * line_height}"
                    f"^A0N,{op['font_size']},{int(op['font_size'] * 0.95)}"
                    f"^FD{line}^FS")
            return ''.join(commands)
        image = self._render_text_image(op['value'], op['font_size'], op['w'], op['max_lines'])
        x, y = self._text_placement(op, image)
        return f"^FO{x},{y}{self._image_gfa(image)}"

    def _zpl_barcode(self, op):
        return (f"^FO{op['x']},{op['y']}^BY2,2.0,{op['h']}"
                f"^BCN,{op['h']},Y,N,N^FD{op['value']}^FS")

    # ------------------------------------------------------------------
    # CPCL-JSON dialect (PrintServer APP `printserver:cpcl?content=` contract)
    # ------------------------------------------------------------------
    def render_cpcl_json(self, layout, records, copies=1):
        self.env['sn.label.reader'].check_records(records)
        commands = []
        for record in records:
            commands.append({'tag': 'INIT', 'height': layout['height'],
                             'offset': 0, 'copies': copies or 1})
            commands.append({'tag': 'PAGE-WIDTH', 'width': layout['width']})
            for op in self._build_ir(layout, record):
                commands.extend(self._cpcl_op(op))
            commands.append({'tag': 'PRINT'})
        return commands

    def _cpcl_op(self, op):
        kind = op['op']
        if kind == 'box':
            return [{'tag': 'BOX', 'x': op['x'], 'y': op['y'],
                     'xEnd': op['x'] + op['w'], 'yEnd': op['y'] + op['h'],
                     'width': op['t']}]
        if kind == 'line':
            return [{'tag': 'LINE', 'x': op['x1'], 'y': op['y1'],
                     'xEnd': op['x2'], 'yEnd': op['y2'], 'width': op['t']}]
        if kind == 'qr':
            return self._cpcl_qr(op)
        if kind == 'text':
            return self._cpcl_text(op)
        return self._cpcl_barcode(op)

    def _cpcl_qr(self, op):
        if op['bitmap']:
            image = self._render_qr_image(op['value'], op['size'])
            return [{'tag': 'BITMAP', 'x': op['x'], 'y': op['y'],
                     'width': image.width, 'threshold': 127,
                     'value': self._image_base64_png(image)}]
        modules = self._qr_module_count(op['value'])
        unit = max(1, min(10, op['size'] // modules))
        return [{'tag': 'QRCODE', 'level': 'M', 'mode': 'A', 'x': op['x'],
                 'y': op['y'], 'n': 2, 'u': unit, 'value': op['value']}]

    def _cpcl_text(self, op):
        if op['value'].isascii():
            size = max(1, min(10, round(op['font_size'] / CPCL_ASCII_BASE_HEIGHT)))
            lines, _widths, line_height = self._ascii_lines(op)
            total_height = line_height * len(lines)
            y = op['y'] + max(0, (op['h'] - total_height) // 2)
            return [{'tag': 'TEXT', 'font': CPCL_ASCII_FONT, 'bold': size,
                     'x': op['x'], 'y': y + index * line_height, 'value': line}
                    for index, line in enumerate(lines)]
        image = self._render_text_image(op['value'], op['font_size'], op['w'], op['max_lines'])
        x, y = self._text_placement(op, image)
        return [{'tag': 'BITMAP', 'x': x, 'y': y, 'width': image.width,
                 'threshold': 127, 'value': self._image_base64_png(image)}]

    def _cpcl_barcode(self, op):
        return [{'tag': 'BARCODE', 'type': '128', 'width': 2, 'ratio': 1,
                 'height': op['h'], 'x': op['x'], 'y': op['y'],
                 'value': op['value']}]

    # ------------------------------------------------------------------
    # PNG dialect (preview)
    # ------------------------------------------------------------------
    def render_png(self, layout, record):
        return self._png_bytes(self.render_png_image(layout, record))

    def render_png_image(self, layout, record):
        self.env['sn.label.reader'].check_records(record)
        self._check_layout(layout)
        image = Image.new('1', (layout['width'], layout['height']), 1)
        draw = ImageDraw.Draw(image)
        for op in self._build_ir(layout, record):
            kind = op['op']
            if kind == 'box':
                draw.rectangle(
                    [op['x'], op['y'], op['x'] + op['w'], op['y'] + op['h']],
                    outline=0, width=op['t'])
            elif kind == 'line':
                draw.line([op['x1'], op['y1'], op['x2'], op['y2']],
                          fill=0, width=op['t'])
            elif kind == 'qr':
                image.paste(self._render_qr_image(op['value'], op['size']),
                            (op['x'], op['y']))
            elif kind == 'barcode':
                self._draw_barcode_placeholder(draw, op)
            else:
                raster = self._render_text_image(
                    op['value'], op['font_size'], op['w'], op['max_lines'])
                if raster:
                    x, y = self._text_placement(op, raster)
                    image.paste(raster, (x, y))
        return image

    @staticmethod
    def _png_bytes(image):
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        return buffer.getvalue()

    def _draw_barcode_placeholder(self, draw, op):
        # 1D barcodes print via native commands (^BC / BARCODE 128); until a
        # barcode raster library lands the preview only marks the footprint.
        draw.rectangle([op['x'], op['y'], op['x'] + op['w'], op['y'] + op['h']],
                       outline=0, width=DEFAULT_THICKNESS)
        raster = self._render_text_image(op['value'], 20, op['w'] - 8, 1)
        if raster:
            draw.bitmap((op['x'] + 4, op['y'] + (op['h'] - raster.height) // 2), raster)
