import base64
import io

from PIL import Image, ImageDraw

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

ELEMENT_TYPE_SELECTION = [
    ('text', 'Text'),
    ('qrcode', 'QR Code'),
    ('barcode', 'Barcode'),
    ('box', 'Box'),
    ('line', 'Line'),
]

CONTENT_SELECTION = [
    ('fixed', 'Fixed Text'),
    ('field', 'Field'),
]

ALIGN_SELECTION = [
    ('left', 'Left'),
    ('center', 'Center'),
    ('right', 'Right'),
]

RENDERING_SELECTION = [
    ('native', 'Native'),
    ('bitmap', 'Bitmap'),
]

# 203 dpi dot sizes of the common label stocks (K300 consumables)
PAPER_PRESET_SELECTION = [
    ('70x40', '70 × 40 mm'),
    ('60x40', '60 × 40 mm'),
    ('50x30', '50 × 30 mm'),
    ('88x88', '88.6 × 88.6 mm'),
    ('custom', 'Custom'),
]
PAPER_PRESET_SIZES = {
    '70x40': (560, 320),
    '60x40': (480, 320),
    '50x30': (400, 240),
    '88x88': (709, 709),
}


class SnLabelTemplate(models.Model):
    """Designable label layout stored as data (design decision 2).

    ``company_id`` empty = shared by every company; set = private to that
    company. Printers resolve templates company-specific first, global
    second (batch 3 wizard).
    """

    _name = 'sn.label.template'
    _description = 'Label Template'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name, id'
    _check_company_auto = True

    name = fields.Char(required=True, translate=True, tracking=True)
    company_id = fields.Many2one(
        'res.company', string='Company', index=True,
        help='Leave empty to share the template across companies.')
    active = fields.Boolean(default=True, tracking=True)
    model_id = fields.Many2one(
        'ir.model', string='Model', required=True, index=True,
        domain=[('transient', '=', False)], ondelete='cascade')
    model_name = fields.Char(related='model_id.model', store=True, index=True)
    width_dots = fields.Integer(string='Width (dots)', required=True, default=560)
    height_dots = fields.Integer(string='Height (dots)', required=True, default=320)
    dpi = fields.Integer(
        string='DPI', default=203,
        help='Dot density the coordinates are designed for (203 = 8 dots/mm).')
    sn_field = fields.Char(
        string='SN Field', default='sn', required=True,
        help='Name of the record field holding the scanned SN on the PDA '
             'label screen (stock.lot templates use "name").')
    domain = fields.Char(
        string='Record Domain',
        help='Optional filter restricting which records the template '
             'applies to.')
    preview_res_id = fields.Integer(
        string='Preview Record',
        help='Optional record id rendered in the preview; defaults to the '
             'most recent readable record of the model.')
    element_ids = fields.One2many(
        'sn.label.element', 'template_id', string='Elements', copy=True)
    preview_image = fields.Binary(compute='_compute_preview_image', string='Preview')
    paper_preset = fields.Selection(
        PAPER_PRESET_SELECTION, string='Paper Preset', store=False,
        compute='_compute_paper_preset', inverse='_inverse_paper_preset',
        help='Pick a label stock to set width and height; Custom keeps '
             'manual values.')

    _sn_label_template_name_unique = models.Constraint(
        'unique(company_id, name)',
        'The label template name must be unique per company.',
    )

    @api.constrains('width_dots', 'height_dots')
    def _check_page_size(self):
        for template in self:
            if template.width_dots <= 0 or template.height_dots <= 0:
                raise ValidationError(
                    _('The label template width and height must be positive integers.'))

    @api.onchange('model_id')
    def _onchange_model_id(self):
        """Model switch invalidates element field paths and the preview record."""
        self.preview_res_id = False
        for element in self.element_ids:
            element.field_path = False

    # ------------------------------------------------------------------
    # Paper preset (write-through helper over width/height dots)
    # ------------------------------------------------------------------
    @api.depends('width_dots', 'height_dots', 'dpi')
    def _compute_paper_preset(self):
        for template in self:
            current = (template.width_dots, template.height_dots)
            template.paper_preset = next(
                (key for key, size in PAPER_PRESET_SIZES.items() if size == current),
                'custom',
            )

    def _inverse_paper_preset(self):
        for template in self:
            size = PAPER_PRESET_SIZES.get(template.paper_preset)
            if size:
                template.width_dots, template.height_dots = size

    def action_duplicate_template(self):
        """Designer-friendly copy: same layout, suffixed name, ready to edit."""
        self.ensure_one()
        copy = self.copy({'name': _('%s (copy)', self.name)})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Label Template'),
            'res_model': self._name,
            'res_id': copy.id,
            'view_mode': 'form',
        }

    # ------------------------------------------------------------------
    # Layout serialization for the rendering engine
    # ------------------------------------------------------------------
    def _to_layout_dict(self):
        self.ensure_one()
        return {
            'width': self.width_dots,
            'height': self.height_dots,
            'dpi': self.dpi,
            'elements': [
                element._to_layout_element()
                for element in self.element_ids.sorted('sequence')
            ],
        }

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------
    def _preview_record(self):
        self.ensure_one()
        record_model = self.env[self.model_id.model]
        if self.preview_res_id:
            record = record_model.browse(self.preview_res_id).exists()
            if record:
                return record
        return record_model.search([], order='id desc', limit=1)

    def _preview_png_bytes(self):
        self.ensure_one()
        renderer = self.env['sn.label.renderer']
        record = self._preview_record()
        if not record:
            return self._placeholder_png(_('No record available for preview.'))
        return renderer._png_bytes(
            renderer.render_png_image(self._to_layout_dict(), record))

    def _placeholder_png(self, message):
        renderer = self.env['sn.label.renderer']
        image = Image.new('1', (max(240, self.width_dots), 64), 1)
        raster = renderer._render_text_image(message, 20, image.width - 8, 1)
        if raster:
            image.paste(raster, (4, (image.height - raster.height) // 2))
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        return buffer.getvalue()

    @api.depends(
        'width_dots', 'height_dots', 'preview_res_id', 'model_id',
        'element_ids', 'element_ids.sequence', 'element_ids.element_type',
        'element_ids.content', 'element_ids.fixed_text', 'element_ids.field_path',
        'element_ids.x', 'element_ids.y', 'element_ids.width',
        'element_ids.height', 'element_ids.thickness', 'element_ids.font_size',
        'element_ids.max_lines', 'element_ids.align', 'element_ids.rendering')
    def _compute_preview_image(self):
        for template in self:
            try:
                template.preview_image = base64.b64encode(template._preview_png_bytes())
            except (UserError, ValidationError) as error:
                template.preview_image = base64.b64encode(
                    template._placeholder_png(str(error)))


class SnLabelElement(models.Model):
    _name = 'sn.label.element'
    _description = 'Label Element'
    _order = 'sequence, id'
    _rec_name = 'element_type'

    template_id = fields.Many2one(
        'sn.label.template', required=True, ondelete='cascade', index=True)
    template_model_name = fields.Char(
        related='template_id.model_name', store=False,
        help='Model of the parent template, feeding the field path picker.')
    sequence = fields.Integer(default=10)
    element_type = fields.Selection(
        ELEMENT_TYPE_SELECTION, required=True, default='text')
    content = fields.Selection(
        CONTENT_SELECTION, required=True, default='fixed')
    fixed_text = fields.Char(translate=True)
    field_path = fields.Char(
        help='Record field rendered as the element value, dot notation '
             'across many2one hops (e.g. template_id.code).')
    x = fields.Integer(required=True, default=10)
    y = fields.Integer(required=True, default=10)
    width = fields.Integer(required=True, default=100)
    height = fields.Integer(required=True, default=30)
    thickness = fields.Integer(
        default=2, help='Line thickness of box and line elements.')
    font_size = fields.Integer(default=30)
    max_lines = fields.Integer(default=1)
    align = fields.Selection(ALIGN_SELECTION, default='left')
    rendering = fields.Selection(
        RENDERING_SELECTION, default='native',
        help='Native uses the printer QR command; bitmap rasterizes '
             'server-side (Chinese text is always bitmap).')

    @api.model
    def _selection_field_paths(self):
        # legacy helper kept for API consumers; the designer UI uses the
        # core field_selector widget fed by template_model_name
        model_name = self.env.context.get('label_model')
        if not model_name:
            return []
        return self.env['sn.label.reader'].field_path_options(model_name)

    @api.constrains('element_type', 'content', 'fixed_text', 'field_path')
    def _check_content(self):
        for element in self:
            if element.element_type in ('box', 'line'):
                continue
            if element.content == 'fixed':
                if not (element.fixed_text or '').strip():
                    raise ValidationError(
                        _('Fixed text is required for fixed-content elements.'))
            else:
                if not (element.field_path or '').strip():
                    raise ValidationError(
                        _('A field path is required for field-content elements.'))
                self.env['sn.label.reader'].validate_field_path(
                    element.template_id.model_id.model, element.field_path)

    @api.constrains('x', 'y', 'width', 'height', 'font_size', 'max_lines')
    def _check_geometry(self):
        for element in self:
            if min(element.x, element.y, element.width, element.height) < 0:
                raise ValidationError(
                    _('Element coordinates and sizes cannot be negative.'))
            if element.element_type not in ('box', 'line') and (
                    element.width < 1 or element.height < 1):
                raise ValidationError(
                    _('Text, QR code and barcode elements need a positive '
                      'width and height.'))

    def _to_layout_element(self):
        self.ensure_one()
        values = {
            'type': self.element_type,
            'x': self.x,
            'y': self.y,
            'width': self.width,
            'height': self.height,
            'thickness': self.thickness or 2,
        }
        if self.element_type in ('text', 'qrcode', 'barcode'):
            if self.content == 'fixed':
                values['text'] = self.fixed_text or ''
            else:
                values['field_path'] = self.field_path or ''
        if self.element_type == 'text':
            values.update({
                'font_size': self.font_size,
                'max_lines': self.max_lines,
                'align': self.align,
            })
        elif self.element_type == 'qrcode':
            values['rendering'] = self.rendering
        return values
