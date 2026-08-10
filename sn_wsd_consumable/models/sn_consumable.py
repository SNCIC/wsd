from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


CONSUMABLE_TYPE_SELECTION = [
    ('solder_paste', 'Solder Paste'),
    ('red_glue', 'Red Glue'),
    ('flux', 'Flux'),
    ('conformal_coating', 'Conformal Coating'),
    ('solder_bar', 'Solder Bar'),
    ('solder_wire', 'Solder Wire'),
]


class SnConsumableBarcodeRule(models.Model):
    _name = 'sn.consumable.barcode.rule'
    _description = 'Consumable Barcode Rule'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    _check_company_auto = True

    name = fields.Char(string='Rule Name', required=True, tracking=True)
    code = fields.Char(string='Rule Code', required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    prefix = fields.Char(string='Prefix', tracking=True)
    date_token = fields.Selection(
        [
            ('none', 'No Date'),
            ('yymmdd', 'YYMMDD'),
            ('yyyymmdd', 'YYYYMMDD'),
            ('ym', 'YYMM'),
            ('yyyymm', 'YYYYMM'),
        ],
        string='Date Segment',
        default='yyyymmdd',
        required=True,
    )
    sequence_padding = fields.Integer(string='Sequence Padding', default=4, required=True)
    sequence_id = fields.Many2one(
        'ir.sequence',
        string='Sequence',
        readonly=True,
        copy=False,
    )
    note = fields.Text(string='Description')

    _code_company_uniq = models.Constraint(
        'unique(code, company_id)',
        'Barcode rule code must be unique per company.',
    )

    @api.constrains('sequence_padding')
    def _check_sequence_padding(self):
        for record in self:
            if record.sequence_padding <= 0:
                raise ValidationError(_('Sequence padding must be greater than zero.'))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._ensure_sequence()
        return records

    def write(self, vals):
        result = super().write(vals)
        self._ensure_sequence()
        sequence_values = {}
        if 'prefix' in vals or 'date_token' in vals:
            sequence_values['prefix'] = self._build_sequence_prefix()
        if 'sequence_padding' in vals:
            sequence_values['padding'] = self.sequence_padding
        if sequence_values:
            for record in self.filtered('sequence_id'):
                record.sequence_id.write({
                    'prefix': record._build_sequence_prefix(),
                    'padding': record.sequence_padding,
                })
        return result

    def _ensure_sequence(self):
        sequence_model = self.env['ir.sequence']
        for record in self.filtered(lambda item: not item.sequence_id):
            record.sequence_id = sequence_model.create({
                'name': f'{record.name} Sequence',
                'code': f'sn.consumable.barcode.rule.{record.id}',
                'implementation': 'no_gap',
                'prefix': record._build_sequence_prefix(),
                'padding': record.sequence_padding,
                'company_id': record.company_id.id,
            })

    def _build_sequence_prefix(self):
        self.ensure_one()
        token_map = {
            'none': '',
            'yymmdd': '%(y)s%(month)s%(day)s',
            'yyyymmdd': '%(year)s%(month)s%(day)s',
            'ym': '%(y)s%(month)s',
            'yyyymm': '%(year)s%(month)s',
        }
        return f'{self.prefix or ""}{token_map[self.date_token]}'

    def generate_barcode(self):
        self.ensure_one()
        self._ensure_sequence()
        return self.sequence_id.next_by_id()


class SnConsumableTemplate(models.Model):
    _name = 'sn.consumable.template'
    _description = 'Consumable Control Template'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'consumable_code, id'
    _rec_name = 'display_name'
    _check_company_auto = True

    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product',
        required=True,
        check_company=True,
        tracking=True,
        domain="[('active', '=', True), ('type', '=', 'consu')]",
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product Variant',
        related='product_tmpl_id.product_variant_id',
        store=True,
        readonly=True,
    )
    consumable_code = fields.Char(string='Consumable Code', required=True, tracking=True)
    consumable_type = fields.Selection(
        CONSUMABLE_TYPE_SELECTION,
        string='Consumable Type',
        required=True,
        tracking=True,
    )
    consumable_name = fields.Char(string='Consumable Name', tracking=True)
    safety_stock = fields.Float(string='Safety Stock', required=True, default=0.0, tracking=True)
    barcode_rule_id = fields.Many2one(
        'sn.consumable.barcode.rule',
        string='Barcode Rule',
        required=True,
        check_company=True,
        tracking=True,
    )
    specification = fields.Char(string='Specification')
    safety_stock_uom_id = fields.Many2one(
        'uom.uom',
        string='Safety Stock Unit',
        required=True,
    )
    vendor_id = fields.Many2one(
        'res.partner',
        string='Vendor',
        check_company=True,
        tracking=True,
    )
    paste_red_glue_control = fields.Selection(
        [
            ('none', 'No Check'),
            ('full', 'Check Warm-up, Stirring, Adhesion Test, Opening, and Shelf Life'),
        ],
        string='Solder Paste and Red Glue Control',
        default='none',
        required=True,
    )
    expiry_control = fields.Selection(
        [
            ('none', 'No Check'),
            ('check', 'Check Shelf Life'),
        ],
        string='Shelf Life Control',
        default='check',
        required=True,
    )
    batch_control = fields.Selection(
        [
            ('none', 'No Check'),
            ('check', 'Check Batch'),
        ],
        string='Batch Control',
        default='check',
        required=True,
    )
    warmup_duration_min = fields.Integer(string='Minimum Warm-up Duration (min)')
    warmup_duration_max = fields.Integer(string='Maximum Warm-up Duration (min)', required=True)
    stirring_duration_min = fields.Integer(string='Minimum Stirring Duration (min)')
    stirring_duration_max = fields.Integer(string='Maximum Stirring Duration (min)')
    shelf_life_days = fields.Integer(string='Shelf Life (Days)', required=True)
    expiry_reminder_days = fields.Integer(string='Expiry Reminder Days', required=True)
    max_warmup_count = fields.Integer(string='Warm-up Count')
    stirring_control = fields.Boolean(string='Stirring Control')
    adhesion_control = fields.Boolean(string='Adhesion Control')
    info_ids = fields.One2many(
        'sn.consumable.info',
        'template_id',
        string='Consumable Info',
    )
    info_count = fields.Integer(
        string='Consumable Quantity',
        compute='_compute_info_count',
    )
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
    )

    _product_type_company_uniq = models.Constraint(
        'unique(product_tmpl_id, consumable_type, company_id)',
        'Only one consumable template is allowed for the same product and consumable type in a company.',
    )

    @api.depends('consumable_code', 'consumable_name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = ' - '.join(
                item for item in [record.consumable_code, record.consumable_name] if item
            )

    @api.depends('info_ids')
    def _compute_info_count(self):
        for record in self:
            record.info_count = len(record.info_ids)

    @api.onchange('product_tmpl_id')
    def _onchange_product_tmpl_id(self):
        for record in self:
            product = record.product_tmpl_id
            if not product:
                continue
            record.consumable_code = product.default_code or False
            record.consumable_name = product.name or False
            if not record.safety_stock_uom_id:
                record.safety_stock_uom_id = product.uom_id
            if not record.vendor_id and product.seller_ids:
                record.vendor_id = product.seller_ids[:1].partner_id

    @api.constrains(
        'safety_stock',
        'warmup_duration_min',
        'warmup_duration_max',
        'stirring_duration_min',
        'stirring_duration_max',
        'shelf_life_days',
        'expiry_reminder_days',
        'max_warmup_count',
    )
    def _check_numeric_values(self):
        for record in self:
            numeric_values = {
                _('Safety stock'): record.safety_stock,
                _('Warm-up duration min'): record.warmup_duration_min,
                _('Warm-up duration max'): record.warmup_duration_max,
                _('Stirring duration min'): record.stirring_duration_min,
                _('Stirring duration max'): record.stirring_duration_max,
                _('Shelf life days'): record.shelf_life_days,
                _('Expiry reminder days'): record.expiry_reminder_days,
                _('Max warm-up count'): record.max_warmup_count,
            }
            for label, value in numeric_values.items():
                if value and value < 0:
                    raise ValidationError(_('%s cannot be negative.', label))
            if record.warmup_duration_min and record.warmup_duration_max and record.warmup_duration_min > record.warmup_duration_max:
                raise ValidationError(_('Warm-up duration min cannot be greater than warm-up duration max.'))
            if record.stirring_duration_min and record.stirring_duration_max and record.stirring_duration_min > record.stirring_duration_max:
                raise ValidationError(_('Stirring duration min cannot be greater than stirring duration max.'))

    def action_view_infos(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Consumable Info'),
            'res_model': 'sn.consumable.info',
            'view_mode': 'list,form',
            'domain': [('template_id', '=', self.id)],
            'context': {'default_template_id': self.id},
        }


class SnConsumableInfo(models.Model):
    _name = 'sn.consumable.info'
    _description = 'Consumable Info'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'
    _rec_name = 'name'
    _check_company_auto = True

    name = fields.Char(string='Consumable SN', required=True, copy=False, default=lambda self: _('New'), tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    template_id = fields.Many2one(
        'sn.consumable.template',
        string='Consumable Control Template',
        required=True,
        check_company=True,
        tracking=True,
    )
    status = fields.Selection(
        [
            ('draft', 'Draft'),
            ('in_stock', 'In Stock'),
            ('reserved', 'Reserved'),
            ('warming', 'Warming'),
            ('stirred', 'Stirred'),
            ('issued', 'Issued'),
            ('opened', 'Opened'),
            ('recycled', 'Recycled'),
            ('exhausted', 'Exhausted'),
            ('expired', 'Expired'),
            ('scrapped', 'Scrapped'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
    )
    is_second_recycled = fields.Boolean(string='Second Recycled', tracking=True)
    consumable_code = fields.Char(string='Consumable Code', related='template_id.consumable_code', store=True, readonly=True)
    consumable_name = fields.Char(string='Consumable Name', related='template_id.consumable_name', store=True, readonly=True)
    specification = fields.Char(string='Specification', related='template_id.specification', store=True, readonly=True)
    consumable_type = fields.Selection(
        related='template_id.consumable_type',
        string='Consumable Type',
        store=True,
        readonly=True,
    )
    vendor_id = fields.Many2one(
        'res.partner',
        string='Vendor',
        related='template_id.vendor_id',
        store=True,
        readonly=True,
    )
    max_warmup_count = fields.Integer(string='Maximum Warm-up Count', related='template_id.max_warmup_count', store=True, readonly=True)
    warmup_count = fields.Integer(string='Warm-up Count', default=0, tracking=True)
    production_lot_no = fields.Char(string='Production Lot No.', tracking=True)
    production_date = fields.Date(string='Production Date', tracking=True)
    expiry_date = fields.Date(string='Expiry Date', tracking=True)
    open_datetime = fields.Datetime(string='Opening Time', tracking=True)
    reserve_datetime = fields.Datetime(string='Reservation Time', tracking=True)
    issue_datetime = fields.Datetime(string='Issue Time', tracking=True)
    unload_datetime = fields.Datetime(string='Unload Time', tracking=True)
    warmup_start_datetime = fields.Datetime(string='Warm-up Start Time', tracking=True)
    warmup_end_datetime = fields.Datetime(string='Warm-up End Time', tracking=True)
    stirring_datetime = fields.Datetime(string='Stirring Time', tracking=True)
    adhesion_test_result = fields.Selection(
        [('pass', 'Pass'), ('fail', 'Fail')],
        string='Adhesion Test',
        tracking=True,
    )
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product',
        related='template_id.product_tmpl_id',
        store=True,
        readonly=True,
    )
    note = fields.Text(string='Notes')
    is_expired = fields.Boolean(
        string='Expired',
        compute='_compute_is_expired',
        store=True,
    )

    _name_company_uniq = models.Constraint(
        'unique(name, company_id)',
        'Consumable SN must be unique per company.',
    )

    @api.depends('expiry_date')
    def _compute_is_expired(self):
        today = fields.Date.context_today(self)
        for record in self:
            record.is_expired = bool(record.expiry_date and record.expiry_date < today)

    @api.onchange('template_id')
    def _onchange_template_id(self):
        for record in self:
            if record.template_id and not record.expiry_date and record.production_date and record.template_id.shelf_life_days:
                record.expiry_date = fields.Date.add(
                    record.production_date,
                    days=record.template_id.shelf_life_days,
                )

    @api.onchange('production_date', 'template_id')
    def _onchange_production_date(self):
        for record in self:
            if record.production_date and record.template_id.shelf_life_days:
                record.expiry_date = fields.Date.add(
                    record.production_date,
                    days=record.template_id.shelf_life_days,
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            template = False
            if vals.get('template_id'):
                template = self.env['sn.consumable.template'].browse(vals['template_id'])
            if vals.get('name', _('New')) == _('New') and template and template.barcode_rule_id:
                vals['name'] = template.barcode_rule_id.generate_barcode()
            if not vals.get('expiry_date') and vals.get('production_date') and template and template.shelf_life_days:
                production_date = fields.Date.to_date(vals['production_date'])
                vals['expiry_date'] = fields.Date.add(production_date, days=template.shelf_life_days)
        records = super().create(vals_list)
        records._update_expired_status()
        return records

    def write(self, vals):
        result = super().write(vals)
        if {'expiry_date', 'status'} & set(vals):
            self._update_expired_status()
        return result

    def _update_expired_status(self):
        today = fields.Date.context_today(self)
        for record in self:
            if record.expiry_date and record.expiry_date < today and record.status not in ('scrapped', 'recycled'):
                record.status = 'expired'

    @api.constrains('warmup_count', 'max_warmup_count')
    def _check_warmup_count(self):
        for record in self:
            if record.warmup_count < 0:
                raise ValidationError(_('Warm-up count cannot be negative.'))
            if record.max_warmup_count and record.warmup_count > record.max_warmup_count:
                raise ValidationError(_('Warm-up count cannot exceed the configured max warm-up count.'))

    @api.constrains('production_date', 'expiry_date')
    def _check_dates(self):
        for record in self:
            if record.production_date and record.expiry_date and record.expiry_date < record.production_date:
                raise ValidationError(_('Expiry date cannot be earlier than production date.'))

    def action_mark_in_stock(self):
        self.write({'status': 'in_stock'})

    def action_reserve(self):
        self.write({
            'status': 'reserved',
            'reserve_datetime': fields.Datetime.now(),
        })

    def action_start_warmup(self):
        self.write({
            'status': 'warming',
            'warmup_start_datetime': fields.Datetime.now(),
        })

    def action_finish_warmup(self):
        for record in self:
            record.write({
                'status': 'stirred' if record.template_id.stirring_control else 'issued',
                'warmup_end_datetime': fields.Datetime.now(),
            })
        return True

    def action_stir(self):
        self.write({
            'status': 'stirred',
            'stirring_datetime': fields.Datetime.now(),
        })

    def action_issue(self):
        self.write({
            'status': 'issued',
            'issue_datetime': fields.Datetime.now(),
        })

    def action_open(self):
        self.write({
            'status': 'opened',
            'open_datetime': fields.Datetime.now(),
        })

    def action_unload(self):
        self.write({
            'status': 'issued',
            'unload_datetime': fields.Datetime.now(),
        })

    def action_mark_recycled(self):
        self.write({'status': 'recycled', 'is_second_recycled': True})

    def action_mark_exhausted(self):
        self.write({'status': 'exhausted'})

    def action_mark_scrapped(self):
        self.write({'status': 'scrapped'})
        return True
