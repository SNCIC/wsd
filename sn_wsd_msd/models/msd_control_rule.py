from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.fields import Domain


class SnMsdControlRule(models.Model):
    _name = 'sn.msd.control.rule'
    _description = 'MSD Control Rule'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'msl_level_id, thickness_min, thickness_max, bake_temperature'
    _check_company_auto = True

    name = fields.Char(compute='_compute_name', store=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    msl_level_id = fields.Many2one(
        'sn.msd.level',
        string='MSL Level',
        required=True,
        tracking=True,
    )
    thickness_min = fields.Float(string='Minimum Thickness', required=True, tracking=True)
    thickness_max = fields.Float(string='Maximum Thickness', required=True, tracking=True)
    standard_exposure_minutes = fields.Integer(
        string='Standard Exposure Minutes',
        related='msl_level_id.standard_exposure_minutes',
        store=True,
        readonly=True,
    )
    cumulative_exposure_minutes = fields.Integer(
        string='Cumulative Exposure Minutes',
        related='msl_level_id.cumulative_exposure_minutes',
        store=True,
        readonly=True,
    )
    bake_total_minutes = fields.Integer(string='Bake Total Minutes', required=True, tracking=True)
    bake_count_limit = fields.Integer(string='Bake Count Limit', required=True, tracking=True)
    bake_temperature = fields.Float(string='Bake Temperature', required=True, tracking=True)
    bake_duration_min = fields.Integer(string='Minimum Bake Minutes', required=True, tracking=True)
    bake_duration_max = fields.Integer(string='Maximum Bake Minutes', required=True, tracking=True)

    _positive_thickness_min = models.Constraint(
        'CHECK(thickness_min >= 0)',
        'The minimum thickness must be greater than or equal to zero.',
    )
    _positive_bake_total = models.Constraint(
        'CHECK(bake_total_minutes > 0)',
        'The bake total minutes must be greater than zero.',
    )
    _positive_bake_count_limit = models.Constraint(
        'CHECK(bake_count_limit > 0)',
        'The bake count limit must be greater than zero.',
    )
    _positive_bake_duration_min = models.Constraint(
        'CHECK(bake_duration_min > 0)',
        'The minimum bake minutes must be greater than zero.',
    )

    @api.depends('msl_level_id.name', 'thickness_min', 'thickness_max', 'bake_temperature')
    def _compute_name(self):
        for rule in self:
            if rule.msl_level_id:
                rule.name = '%s / %s-%s / %s' % (
                    rule.msl_level_id.name,
                    rule.thickness_min,
                    rule.thickness_max,
                    rule.bake_temperature,
                )
            else:
                rule.name = False

    @api.constrains('thickness_min', 'thickness_max')
    def _check_thickness_range(self):
        for rule in self:
            if rule.thickness_max <= rule.thickness_min:
                raise ValidationError(_('The maximum thickness must be greater than the minimum thickness.'))

    @api.constrains('bake_duration_min', 'bake_duration_max')
    def _check_bake_duration_range(self):
        for rule in self:
            if rule.bake_duration_max < rule.bake_duration_min:
                raise ValidationError(_('The maximum bake minutes cannot be less than the minimum bake minutes.'))
            if rule.bake_total_minutes < rule.bake_duration_min:
                raise ValidationError(_('The total bake minutes cannot be less than the minimum bake minutes.'))

    @api.constrains('msl_level_id', 'thickness_min', 'thickness_max', 'company_id', 'active')
    def _check_no_overlapping_thickness(self):
        for rule in self.filtered('active'):
            domain = Domain([
                ('id', '!=', rule.id),
                ('active', '=', True),
                ('msl_level_id', '=', rule.msl_level_id.id),
                ('company_id', '=', rule.company_id.id),
                ('thickness_min', '<', rule.thickness_max),
                ('thickness_max', '>', rule.thickness_min),
            ])
            if self.search_count(domain, limit=1):
                raise ValidationError(_('MSD control rule thickness ranges cannot overlap for the same MSL level.'))

    @api.model
    def _match_rule(self, product, company=False):
        if not product or not product.is_msd_material:
            return self.env['sn.msd.control.rule']
        if not product.msl_level_id or product.component_thickness <= 0:
            return self.env['sn.msd.control.rule']
        company = company or self.env.company
        return self.search([
            ('active', '=', True),
            ('company_id', '=', company.id),
            ('msl_level_id', '=', product.msl_level_id.id),
            ('thickness_min', '<=', product.component_thickness),
            ('thickness_max', '>=', product.component_thickness),
        ], limit=1)
