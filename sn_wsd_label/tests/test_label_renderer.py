import base64
import binascii
import io
import json
import re

from PIL import Image, ImageChops

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


def decode_gfa(hex_data, row_bytes):
    data = binascii.unhexlify(hex_data)
    height = len(data) // row_bytes
    image = Image.new('1', (row_bytes * 8, height))
    pixels = image.load()
    for y in range(height):
        for byte_index in range(row_bytes):
            byte = data[y * row_bytes + byte_index]
            for bit in range(8):
                pixels[byte_index * 8 + bit, y] = 0 if (byte >> (7 - bit)) & 1 else 1
    return image


@tagged('post_install', '-at_install')
class TestLabelRenderer(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.renderer = cls.env['sn.label.renderer']
        cls.reader = cls.env['sn.label.reader']
        cls.partner = cls.env['res.partner'].create({
            'name': '钢网测试 SN-0001',
            'street': 'No.1 Workshop Road',
            'company_id': cls.env.company.id,
        })
        cls.layout = {
            'width': 560, 'height': 320, 'dpi': 203,
            'elements': [
                {'type': 'box', 'x': 8, 'y': 8, 'width': 544, 'height': 304,
                 'thickness': 2},
                {'type': 'line', 'x': 8, 'y': 60, 'width': 544, 'height': 0,
                 'thickness': 2},
                {'type': 'text', 'x': 20, 'y': 20, 'width': 100, 'height': 30,
                 'font_size': 24, 'text': '工具码'},
                {'type': 'text', 'x': 130, 'y': 20, 'width': 240, 'height': 30,
                 'font_size': 26, 'field_path': 'name'},
                {'type': 'text', 'x': 20, 'y': 80, 'width': 240, 'height': 30,
                 'font_size': 24, 'align': 'center', 'field_path': 'street'},
                {'type': 'qrcode', 'x': 400, 'y': 70, 'width': 120,
                 'height': 120, 'field_path': 'name'},
                {'type': 'qrcode', 'x': 400, 'y': 210, 'width': 100,
                 'height': 100, 'text': 'BITMAP-QR', 'rendering': 'bitmap'},
                {'type': 'barcode', 'x': 20, 'y': 240, 'width': 300,
                 'height': 60, 'text': 'ABC-123'},
            ],
        }

    # ------------------------------------------------------------------
    # ZPL dialect
    # ------------------------------------------------------------------
    def test_zpl_structure(self):
        zpl = self.renderer.render_zpl(self.layout, self.partner)
        self.assertTrue(zpl.startswith('^XA'))
        self.assertTrue(zpl.rstrip().endswith('^XZ'))
        self.assertIn('^PW560', zpl)
        self.assertIn('^LL320', zpl)
        self.assertIn('^FO8,8^GB544,304,2^FS', zpl)
        self.assertIn('^GB544,2,2^FS', zpl)          # horizontal line
        self.assertIn('^GFA,', zpl)                  # Chinese text bitmap
        self.assertIn('^BQN,2,', zpl)                # native QR
        self.assertIn('^A0N,', zpl)                  # native ASCII font
        self.assertIn('^BCN,', zpl)                  # native CODE128
        self.assertNotIn('工具码', zpl)               # Chinese is raster-only

    def test_zpl_multiple_records_and_copies(self):
        other = self.env['res.partner'].create({'name': '第二张'})
        zpl = self.renderer.render_zpl(self.layout, self.partner + other, copies=2)
        self.assertEqual(zpl.count('^XA'), 2)
        self.assertEqual(zpl.count('^XZ'), 2)
        self.assertEqual(zpl.count('^PQ2'), 2)

    def test_zpl_bitmap_qr_uses_gfa(self):
        zpl = self.renderer.render_zpl(self.layout, self.partner)
        self.assertNotIn('BITMAP-QR', zpl)  # bitmap QR value never in ^FD
        self.assertRegex(zpl, r'\^GFA,')

    # ------------------------------------------------------------------
    # CPCL-JSON dialect
    # ------------------------------------------------------------------
    def test_cpcl_structure(self):
        commands = self.renderer.render_cpcl_json(self.layout, self.partner, copies=2)
        tags = [command['tag'] for command in commands]
        contract = {'INIT', 'PAGE-WIDTH', 'TEXT', 'BOX', 'LINE', 'QRCODE',
                    'BITMAP', 'BARCODE', 'PRINT'}
        self.assertTrue(set(tags) <= contract)
        self.assertEqual(tags[0], 'INIT')
        self.assertEqual(commands[0]['copies'], 2)
        self.assertEqual(commands[0]['height'], 320)
        self.assertEqual(tags[1], 'PAGE-WIDTH')
        self.assertEqual(commands[1]['width'], 560)
        self.assertEqual(tags[-1], 'PRINT')
        for tag in ('BOX', 'QRCODE', 'BITMAP', 'TEXT', 'BARCODE', 'LINE'):
            self.assertIn(tag, tags)
        for command in commands:
            if command['tag'] == 'BITMAP':
                self.assertTrue(
                    command['value'].startswith('data:image/png;base64,'))
        json.dumps(commands)  # must be jsonrpc-serializable

    def test_cpcl_multiple_records(self):
        other = self.env['res.partner'].create({'name': '第二张'})
        commands = self.renderer.render_cpcl_json(
            self.layout, self.partner + other)
        tags = [command['tag'] for command in commands]
        self.assertEqual(tags.count('INIT'), 2)
        self.assertEqual(tags.count('PRINT'), 2)

    # ------------------------------------------------------------------
    # PNG dialect
    # ------------------------------------------------------------------
    def test_png_size(self):
        png_bytes = self.renderer.render_png(self.layout, self.partner)
        self.assertTrue(png_bytes.startswith(b'\x89PNG'))
        image = Image.open(io.BytesIO(png_bytes))
        self.assertEqual(image.size, (560, 320))

    # ------------------------------------------------------------------
    # Same-source raster across dialects
    # ------------------------------------------------------------------
    def test_chinese_text_same_raster_in_all_dialects(self):
        expected = self.renderer._render_text_image('工具码', 24, 100, 1)
        zpl = self.renderer.render_zpl(self.layout, self.partner)
        match = re.search(
            r'\^GFA,(\d+),(\d+),(\d+),([0-9A-F]+)\^FS', zpl)
        self.assertIsNotNone(match)
        row_bytes = int(match.group(3))
        decoded = decode_gfa(match.group(4), row_bytes)
        self.assertIsNone(ImageChops.difference(
            decoded.crop((0, 0, expected.width, expected.height)),
            expected).getbbox())

        commands = self.renderer.render_cpcl_json(self.layout, self.partner)
        bitmaps = [c for c in commands if c['tag'] == 'BITMAP']
        self.assertTrue(bitmaps)
        payload = base64.b64decode(
            bitmaps[0]['value'].split(',', 1)[1])
        cpcl_image = Image.open(io.BytesIO(payload))
        if cpcl_image.mode != '1':
            # explicit threshold: convert('1') would dither a grayscale PNG
            cpcl_image = cpcl_image.convert('L').point(
                lambda v: 255 if v >= 128 else 0, mode='1')
        # PIL mode '1' uses 0/1 in memory but 0/255 after a PNG roundtrip:
        # compare through mode 'L' so both sides use the same value scale.
        self.assertEqual(cpcl_image.convert('L').tobytes(),
                         expected.convert('L').tobytes())

    # ------------------------------------------------------------------
    # Field reader
    # ------------------------------------------------------------------
    def test_reader_valid_paths(self):
        self.assertEqual(self.reader.read_value(self.partner, 'name'),
                         '钢网测试 SN-0001')
        company_name = self.reader.read_value(self.partner, 'company_id.name')
        self.assertTrue(company_name)
        self.assertEqual(
            self.reader.read_value(self.partner, 'street'),
            'No.1 Workshop Road')
        # regression: the terminal field may not exist on the ROOT model —
        # formatting must use the record that owns it (sn.label.template has
        # model_name, not model)
        template = self.env['sn.label.template'].create({
            'name': 'Reader Regression',
            'model_id': self.env['ir.model']._get_id('res.partner'),
        })
        self.assertEqual(
            self.reader.read_value(template, 'model_id.model'), 'res.partner')

    def test_reader_rejects_invalid_paths(self):
        with self.assertRaises(ValidationError):
            self.reader.validate_field_path('res.partner', 'message_ids')
        with self.assertRaises(ValidationError):
            self.reader.validate_field_path('res.partner', 'name.foo')
        with self.assertRaises(ValidationError):
            self.reader.validate_field_path('res.partner', 'unknown_field')
        with self.assertRaises(ValidationError):
            self.reader.validate_field_path('res.partner', '')

    def test_reader_enforces_record_access(self):
        cron = self.env['ir.cron'].create({
            'name': 'Label Test Cron',
            'state': 'code',
            'code': 'True',
            'model_id': self.env.ref('base.model_res_partner').id,
            'interval_number': 1,
        })
        demo_user = self.env.ref('base.user_demo')
        with self.assertRaises(AccessError):
            self.renderer.with_user(demo_user).render_zpl(
                {'width': 100, 'height': 50,
                 'elements': [{'type': 'text', 'x': 0, 'y': 0, 'width': 80,
                               'height': 20, 'text': 'X'}]},
                cron.with_user(demo_user))
