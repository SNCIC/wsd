from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SnMsdLevel(models.Model):
    _name = 'sn.msd.level'
    _description = 'MSD MSL Level'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, name'

    name = fields.Char(string='MSL Level', required=True, tracking=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    standard_exposure_minutes = fields.Integer(
        string='Standard Exposure Minutes',
        required=True,
        tracking=True,
    )
    warning_exposure_minutes = fields.Integer(
        string='Warning Exposure Minutes',
        required=True,
        tracking=True,
    )
    cumulative_exposure_minutes = fields.Integer(
        string='Cumulative Exposure Minutes',
        required=True,
        tracking=True,
    )

    _unique_name = models.UniqueIndex('(name)')
    _positive_standard_exposure = models.Constraint(
        'CHECK(standard_exposure_minutes > 0)',
        'The standard exposure minutes must be greater than zero.',
    )
    _positive_warning_exposure = models.Constraint(
        'CHECK(warning_exposure_minutes >= 0)',
        'The warning exposure minutes must be greater than or equal to zero.',
    )
    _positive_cumulative_exposure = models.Constraint(
        'CHECK(cumulative_exposure_minutes > 0)',
        'The cumulative exposure minutes must be greater than zero.',
    )

    @api.constrains('warning_exposure_minutes', 'standard_exposure_minutes')
    def _check_warning_exposure_minutes(self):
        for level in self:
            if level.warning_exposure_minutes > level.standard_exposure_minutes:
                raise ValidationError(_('The warning exposure minutes cannot exceed the standard exposure minutes.'))
