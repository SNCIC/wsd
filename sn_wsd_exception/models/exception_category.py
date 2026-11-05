from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

LEVEL_SELECTION = [
    ('normal', 'Normal'),
    ('urgent', 'Urgent'),
    ('critical', 'Critical'),
]


class SnWsdExceptionCategory(models.Model):
    _name = 'sn.wsd.exception.category'
    _description = 'SN WSD Exception Category'
    _order = 'parent_id, sequence, id'
    _rec_name = 'complete_name'
    _check_company_auto = True

    name = fields.Char(string='Category', required=True, translate=True)
    complete_name = fields.Char(compute='_compute_complete_name', recursive=True, store=True, translate=True)
    code = fields.Char(string='Code', index=True, copy=False)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    parent_id = fields.Many2one(
        'sn.wsd.exception.category',
        string='Parent Category',
        index=True,
        ondelete='restrict',
        check_company=True,
    )
    child_ids = fields.One2many('sn.wsd.exception.category', 'parent_id', string='Subcategories')
    default_team_id = fields.Many2one(
        'sn.wsd.exception.team',
        string='Default Responsible Team',
        check_company=True,
        ondelete='set null',
        help='Routing target used when a ticket is created with this root category.',
    )
    default_level = fields.Selection(
        LEVEL_SELECTION,
        string='Default Level',
        default='normal',
        help='Severity preset applied on ticket creation; the claimer can adjust it.',
    )
    description = fields.Text(string='Description')

    _code_company_uniq = models.Constraint(
        'unique(company_id, code)',
        'The exception category code must be unique per company.',
    )

    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for category in self:
            if category.parent_id:
                category.complete_name = f'{category.parent_id.complete_name} / {category.name}'
            else:
                category.complete_name = category.name

    @api.constrains('parent_id')
    def _check_category_depth(self):
        for category in self:
            if category.parent_id and category.parent_id.parent_id:
                raise ValidationError(_('The exception category tree is limited to two levels (category / subcategory).'))

    @api.constrains('name', 'parent_id', 'company_id')
    def _check_name_unique_in_parent(self):
        for category in self:
            domain = [
                ('id', '!=', category.id),
                ('company_id', '=', category.company_id.id),
                ('parent_id', '=', category.parent_id.id if category.parent_id else False),
                ('name', '=', category.name),
            ]
            if self.search_count(domain):
                raise ValidationError(_('The exception category name must be unique inside its parent category.'))
