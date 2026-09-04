import binascii
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import qrcode
from markupsafe import Markup

from odoo import _, models
from odoo.exceptions import UserError


class ReportIncomingMaterialLabelZpl(models.AbstractModel):
    _name = 'report.sn_wsd_stock.report_incoming_material_label_zpl'
    _description = 'Incoming Material Label ZPL Report'

    @staticmethod
    def _clean_zpl_text(value):
        text = str(value or '').replace('^', ' ').replace('~', ' ')
        return ' '.join(text.split())

    @staticmethod
    def _format_quantity(value):
        quantity = f'{float(value or 0):.6f}'.rstrip('0').rstrip('.')
        return quantity or '0'

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
    def _render_text_gfa(cls, value, font_size, max_width, max_lines=1):
        text = cls._clean_zpl_text(value)
        if not text:
            return ''
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

        return cls._image_gfa(image)

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
    def _render_qr_gfa(cls, value, cell_width, cell_height):
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=1,
            border=2,
        )
        qr.add_data(cls._clean_zpl_text(value))
        qr.make(fit=True)
        qr_image = qr.make_image(fill_color='black', back_color='white').convert('1')
        margin = 18
        size = min(cell_width - margin * 2, cell_height - margin * 2)
        qr_image = qr_image.resize((size, size), Image.Resampling.NEAREST)
        return cls._image_gfa(qr_image)

    @classmethod
    def _field_image(cls, value, x, cell_top, cell_height, font_size, max_width, max_lines=1):
        image = cls._render_text_gfa(value, font_size, max_width, max_lines)
        if not image:
            return ''
        parts = image.split(',', 4)
        row_bytes = int(parts[3])
        hex_data = parts[4].split('^FS', 1)[0]
        image_height = len(hex_data) // 2 // row_bytes
        y = cell_top + max(0, (cell_height - image_height) // 2)
        return f'^FO{x},{y}{image}'

    @classmethod
    def _label_images(cls, labels):
        return {
            'material_code_label': Markup(cls._field_image(labels['material_code'], 35, 20, 135, 34, 100)),
            'batch_label': Markup(cls._field_image(labels['batch'], 445, 20, 135, 34, 55)),
            'material_name_label': Markup(cls._field_image(labels['material_name'], 35, 155, 135, 34, 100)),
            'quantity_label': Markup(cls._field_image(labels['quantity'], 445, 155, 135, 34, 55)),
            'specification_label': Markup(cls._field_image(labels['specification'], 35, 290, 135, 34, 100)),
            'supplier_label': Markup(cls._field_image(labels['supplier'], 35, 425, 135, 34, 100)),
        }

    def _get_report_values(self, docids, data=None):
        lots = self.env['stock.lot'].browse(docids).exists()
        if not lots:
            raise UserError(_('No material lots were selected for label printing.'))
        for lot in lots:
            lot.label_print_count += 1

        titles = {
            'material_code': _('Material Code'),
            'batch': _('Batch'),
            'material_name': _('Material Name'),
            'quantity': _('Quantity Label'),
            'specification': _('Specification'),
            'supplier': _('Supplier Label'),
        }
        labels = []
        for lot in lots:
            label = self._label_images(titles)
            label.update({
                'material_code': Markup(self._field_image(lot.product_id.default_code, 157, 20, 135, 38, 270, 2)),
                'batch_no': Markup(self._field_image(lot.supplier_batch_no, 515, 20, 135, 32, 166, 2)),
                'material_name': Markup(self._field_image(lot.product_id.name, 157, 155, 135, 32, 270, 2)),
                'quantity': Markup(self._field_image(self._format_quantity(lot.initial_quantity), 515, 155, 135, 36, 166, 2)),
                'specification': Markup(self._field_image(lot.product_id.material_specification, 157, 290, 135, 30, 270, 2)),
                'supplier_name': Markup(self._field_image(lot.supplier_name, 157, 425, 135, 30, 270, 2)),
                'material_sn': Markup(self._field_image(lot.name, 35, 560, 129, 30, 654, 2)),
                'qr_image': Markup(self._render_qr_gfa(lot.name, 255, 270)),
            })
            labels.append(label)
        return {'doc_ids': lots.ids, 'doc_model': 'stock.lot', 'docs': lots, 'labels': labels}
