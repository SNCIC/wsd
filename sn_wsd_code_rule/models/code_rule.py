import ast
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

SEGMENT_TYPE_SELECTION = [
    ('fixed', 'Fixed Text'),
    ('field', 'Field Value'),
    ('lookup', 'Lookup'),
    ('date', 'Date'),
    ('seq', 'Sequence'),
]

PERIOD_SELECTION = [
    ('none', 'No Reset'),
    ('year', 'Yearly'),
    ('month', 'Monthly'),
    ('day', 'Daily'),
]

EMPTY_POLICY_SELECTION = [
    ('error', 'Raise Error'),
    ('blank', 'Empty String'),
]

SEQ_IMPL_SELECTION = [
    ('engine', 'Engine Counter'),
    ('sequence', 'ir.sequence'),
]

DATE_SOURCE_SELECTION = [
    ('today', 'Current Date'),
    ('field', 'Record Date Field'),
]

PLACEHOLDER_PATTERN = re.compile(r'\{\{\s*([A-Za-z0-9_.]+)\s*\}\}')

PERIOD_STRFTIME = {
    'year': '%Y',
    'month': '%Y%m',
    'day': '%Y%m%d',
}


class SnCodeRule(models.Model):
    """Configurable coding rule: ordered segments rendered against a record
    and joined with a separator. Identified by (model, company, optional
    picking type) — deliberately no string code (design decision 2)."""

    _name = 'sn.code.rule'
    _description = 'Document Coding Rule'
    _inherit = ['mail.thread']
    _order = 'model_id, name, id'
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one(
        'res.company', string='Company', index=True,
        help='Leave empty to apply to every company.')
    model_id = fields.Many2one(
        'ir.model', string='Document Model', required=True, index=True,
        domain=[('transient', '=', False)], ondelete='cascade')
    model_name = fields.Char(related='model_id.model', store=True, index=True)
    picking_type_id = fields.Many2one(
        'stock.picking.type', string='Operation Type', index=True,
        help='Only used when the model is stock.picking: distinguishes '
             'rules for issue/receipt/return/over-pick documents.')
    target_field = fields.Char(
        string='Target Field', required=True, default='name',
        help='Character field of the document the generated code is '
             'written to.')
    separator = fields.Char(
        default='-', help='String inserted between rendered segments.')
    segment_ids = fields.One2many(
        'sn.code.rule.segment', 'rule_id', string='Segments', copy=True)
    segment_count = fields.Integer(compute='_compute_segment_count')

    @api.depends('segment_ids')
    def _compute_segment_count(self):
        for rule in self:
            rule.segment_count = len(rule.segment_ids)

    @api.constrains('model_id', 'company_id', 'picking_type_id')
    def _check_rule_unique(self):
        for rule in self:
            domain = [
                ('id', '!=', rule.id),
                ('active', '=', True),
                ('model_id', '=', rule.model_id.id),
                ('picking_type_id', '=', rule.picking_type_id.id or False),
            ]
            if rule.company_id:
                domain = domain + [
                    '|', ('company_id', '=', False),
                    ('company_id', '=', rule.company_id.id),
                ]
            else:
                domain.append(('company_id', '=', False))
            if self.search_count(domain):
                raise ValidationError(_(
                    'A coding rule already exists for model %(model)s, '
                    'company %(company)s, operation type %(picking_type)s.',
                    model=rule.model_id.model,
                    company=rule.company_id.display_name or _('All companies'),
                    picking_type=(rule.picking_type_id.display_name
                                  or _('Any')),
                ))

    @api.constrains('picking_type_id', 'model_id')
    def _check_picking_type_scope(self):
        for rule in self:
            if (rule.picking_type_id
                    and rule.model_id.model != 'stock.picking'):
                raise ValidationError(_(
                    'Operation type only applies to stock.picking rules.'))

    # ------------------------------------------------------------------
    # Rule resolution and rendering
    # ------------------------------------------------------------------
    @api.model
    def _find_rule(self, record):
        """Rule for a record being coded: company-specific first, then the
        company-empty global one; operation type must match when set."""
        model = self.env['ir.model']._get_id(record._name)
        domain = [
            ('model_id', '=', model),
            ('active', '=', True),
            '|', ('company_id', '=', False),
            ('company_id', 'in', record.company_id.ids or [False]),
        ]
        if record._name == 'stock.picking':
            domain.append(('picking_type_id', '=', record.picking_type_id.id))
        else:
            domain.append(('picking_type_id', '=', False))
        return self.search(domain, order='company_id desc, id desc', limit=1)

    def render(self, record):
        """Render the code for ``record``; raises on any segment failure or
        on a (model, target field) duplicate. Never returns a half code."""
        self.ensure_one()
        parts = []
        for segment in self.segment_ids.sorted('sequence'):
            parts.append(segment._render(record))
        code = self.separator.join(part for part in parts if part != '')
        if not code:
            return code
        duplicate = self.env[record._name].search_count([
            (self.target_field, '=', code),
            ('id', '!=', record.id),
        ], limit=1)
        if duplicate:
            raise ValidationError(_(
                'Generated code "%(code)s" already exists on another '
                '%(model)s record. Adjust the rule segments or reset '
                'dimensions.',
                code=code, model=record._name))
        return code

    @api.model
    def _seed_manufacturing_rules(self):
        """Seed coding rules for the four manufacturing picking types."""
        picking_model_id = self.env['ir.model']._get_id('stock.picking')
        seeds = [
            ('sn.wsd.mes.picking.issue', 'Material Issue Coding', 'MI'),
            ('sn.wsd.mes.picking.receipt', 'Completion Receipt Coding', 'FR'),
            ('sn.wsd.mes.picking.return', 'Material Return Coding', 'MR'),
            ('sn.wsd.mes.picking.over', 'Over-pick Coding', 'OP'),
        ]
        for sequence_code, rule_name, prefix in seeds:
            pt = self.env['stock.picking.type'].search(
                [('sequence_code', '=', sequence_code)], limit=1)
            if not pt:
                continue
            if self.search_count([
                    ('model_id', '=', picking_model_id),
                    ('picking_type_id', '=', pt.id)]):
                continue
            self.create({
                'name': rule_name,
                'model_id': picking_model_id,
                'picking_type_id': pt.id,
                'target_field': 'name',
                'separator': '-',
                'segment_ids': [
                    (0, 0, {'segment_type': 'fixed', 'text_value': prefix}),
                    (0, 0, {'segment_type': 'date',
                            'date_format': '%Y', 'date_source': 'today'}),
                    (0, 0, {'segment_type': 'seq', 'padding': 4,
                            'period': 'year', 'seq_impl': 'engine'}),
                ],
            })


class SnCodeRuleSegment(models.Model):
    _name = 'sn.code.rule.segment'
    _description = 'Coding Rule Segment'
    _order = 'sequence, id'
    _rec_name = 'segment_type'

    rule_id = fields.Many2one(
        'sn.code.rule', required=True, ondelete='cascade', index=True)
    rule_model_name = fields.Char(
        related='rule_id.model_id.model', store=False,
        help='Model of the parent rule, feeding the field path pickers.')
    sequence = fields.Integer(default=10)
    segment_type = fields.Selection(
        SEGMENT_TYPE_SELECTION, required=True, default='fixed')

    # fixed / field
    text_value = fields.Char(string='Fixed Text')
    field_path = fields.Char(
        help='Record field rendered as the segment value, dot notation '
             'across many2one hops (e.g. picking_id.partner_id.ref).')
    empty_policy = fields.Selection(
        EMPTY_POLICY_SELECTION, default='error', required=True,
        string='When Empty')

    # lookup
    lookup_model_id = fields.Many2one(
        'ir.model', string='Lookup Model', domain=[('transient', '=', False)])
    lookup_domain = fields.Text(
        string='Lookup Domain',
        help='Search domain on the lookup model; {{field_path}} placeholders '
             'are resolved against the coded record first, e.g. '
             "[('x_drawing_no', '=', {{product_id.default_code}})].")
    lookup_field_path = fields.Char(
        string='Lookup Field',
        help='Field path read on the matched lookup record.')

    # date + seq period source
    date_source = fields.Selection(
        DATE_SOURCE_SELECTION, default='today', required=True)
    date_field_path = fields.Char(
        string='Date Field',
        help='Record date used when the source is a field (dot notation); '
             'falls back to today when empty or unset.')
    date_format = fields.Char(
        default='%Y%m%d',
        help='Python strftime codes, e.g. %%Y%%m%%d -> 20260908.')

    # sequence
    padding = fields.Integer(default=5, required=True)
    number_next = fields.Integer(
        string='Start Value', default=1, required=True)
    period = fields.Selection(
        PERIOD_SELECTION, default='none', required=True,
        string='Reset Period')
    group_field_paths = fields.Text(
        string='Reset Group Fields',
        help='One field path per line: the counter restarts whenever any of '
             'these values changes (e.g. product_id.default_code).')
    seq_impl = fields.Selection(
        SEQ_IMPL_SELECTION, default='engine', required=True,
        string='Counter Implementation')
    sequence_code = fields.Char(
        string='ir.sequence Code',
        help='Sequence code called via next_by_code when the implementation '
             'is ir.sequence (keeps counting on an existing sequence).')

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _render(self, record):
        self.ensure_one()
        kind = self.segment_type
        if kind == 'fixed':
            return self.text_value or ''
        if kind == 'field':
            return self._render_field(record)
        if kind == 'lookup':
            return self._render_lookup(record)
        if kind == 'date':
            return self._segment_date(record).strftime(self.date_format)
        return self._render_sequence(record)

    def _reader(self):
        return self.env['sn.field.reader']

    def _render_field(self, record):
        value = self._reader().read_value(record, self.field_path)
        if value == '' and self.empty_policy == 'error':
            raise ValidationError(_(
                'Segment field %(path)s is empty on record %(record)s; set '
                'the empty policy to "Empty String" or fill the field.',
                path=self.field_path, record=record.display_name))
        return value

    def _segment_date(self, record):
        date_value = fields.Date.context_today(self)
        if self.date_source == 'field' and self.date_field_path:
            raw = self._reader().read_value(record, self.date_field_path)
            if raw:
                date_value = fields.Date.to_date(raw)
        return date_value

    def _render_lookup(self, record):
        if not self.lookup_model_id or not self.lookup_field_path:
            raise ValidationError(_(
                'Lookup segment %(segment)s of rule %(rule)s needs a lookup '
                'model, domain and field.',
                segment=self.sequence, rule=self.rule_id.display_name))
        domain_text = self.lookup_domain or '[]'
        resolved = PLACEHOLDER_PATTERN.sub(
            lambda m: repr(self._reader().read_value(record, m.group(1))),
            domain_text,
        )
        try:
            domain = ast.literal_eval(resolved)
        except (ValueError, SyntaxError):
            raise ValidationError(_(
                'Lookup domain of rule %(rule)s segment %(segment)s is not '
                'a valid domain after placeholder resolution: %(domain)s',
                rule=self.rule_id.display_name, segment=self.sequence,
                domain=resolved))
        target = self.env[self.lookup_model_id.model].search(
            domain, order='id desc', limit=1)
        if not target:
            raise ValidationError(_(
                'Lookup segment of rule %(rule)s found no %(model)s record '
                'for domain %(domain)s.',
                rule=self.rule_id.display_name,
                model=self.lookup_model_id.model, domain=resolved))
        return self._reader().read_value(target, self.lookup_field_path)

    def _sequence_key(self, record):
        parts = []
        if self.period != 'none':
            parts.append(self._segment_date(record).strftime(
                PERIOD_STRFTIME[self.period]))
        for path in filter(None, (self.group_field_paths or '').splitlines()):
            path = path.strip()
            if path:
                parts.append(self._reader().read_value(record, path))
        return '|'.join(parts)

    def _render_sequence(self, record):
        if self.seq_impl == 'sequence':
            if not self.sequence_code:
                raise ValidationError(_(
                    'Sequence segment of rule %(rule)s has no ir.sequence '
                    'code configured.', rule=self.rule_id.display_name))
            value = self.env['ir.sequence'].next_by_code(self.sequence_code)
            if not value:
                raise ValidationError(_(
                    'The ir.sequence %(code)s does not exist.',
                    code=self.sequence_code))
            return value
        if self.padding < 1:
            raise ValidationError(_(
                'Sequence padding must be at least 1 (rule %(rule)s).',
                rule=self.rule_id.display_name))
        value = self.env['sn.code.counter']._next_value(self, record)
        return str(value).zfill(self.padding)


class SnCodeCounter(models.Model):
    """Per-(segment, dimension key) counter. A missing row means the key is
    new — counting restarts from the segment start value; that IS the reset
    mechanism (design decision 4)."""

    _name = 'sn.code.counter'
    _description = 'Coding Rule Counter'
    _order = 'segment_id, key'

    segment_id = fields.Many2one(
        'sn.code.rule.segment', required=True, ondelete='cascade', index=True)
    key = fields.Char(required=True, index=True)
    value = fields.Integer(required=True, default=0)

    _counter_uniq = models.Constraint(
        'unique(segment_id, key)',
        'The coding counter key must be unique per segment.',
    )

    def _next_value(self, segment, record):
        """Atomically increment and return the next value for the segment's
        current dimension key (row-level UPDATE serialization makes
        concurrent picks safe; INSERT race resolves via the unique
        constraint)."""
        segment.ensure_one()
        key = segment._sequence_key(record)
        self.env.cr.execute(
            "UPDATE sn_code_counter SET value = value + 1 "
            "WHERE segment_id = %s AND key = %s RETURNING value",
            (segment.id, key),
        )
        row = self.env.cr.fetchone()
        if row:
            return row[0]
        try:
            self.create({
                'segment_id': segment.id,
                'key': key,
                'value': segment.number_next,
            })
        except Exception:
            # concurrent insert won the race: retry the increment
            self.env.cr.rollback()
            self.env.cr.execute(
                "UPDATE sn_code_counter SET value = value + 1 "
                "WHERE segment_id = %s AND key = %s RETURNING value",
                (segment.id, key),
            )
            row = self.env.cr.fetchone()
            if not row:
                raise
            return row[0]
        return segment.number_next
