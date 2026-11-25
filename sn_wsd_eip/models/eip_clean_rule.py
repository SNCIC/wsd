"""EIP collection limit rules (the third cleansing gate).

The spec gives no unified limits: every interface/judge-value pair
carries the factory's own process standard, so the limits live in a
config table. Missing required fields and failing conclusions are
built-in gates; anything configured here additionally bounds the
measured values (out-of-limit rows are rejected, never repaired --
there is no path that turns a failed measurement into a passing one).
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .eip_value_mapping import EIP_VALUE_FIELDS

# value columns a limit can bound: the spec ships these as Decimal;
# text-typed columns (check duration, testing voltage, ...) are out of
# the list on purpose
NUMERIC_VALUE_FIELDS = {
    'current_value',
    'warming_zone',
    'constant_temperature_zone',
    'welding_zone',
    'cooling_zone',
    'preheating_area',
    'agingroom_temperature',
    'standard_value',
    'leakage_current',
    'average_error',
    'real_error',
    'measured_value',
    'error_value',
}

LIMIT_FIELD_SELECTION = [
    item for item in EIP_VALUE_FIELDS if item[0] in NUMERIC_VALUE_FIELDS]


class EipCleanRule(models.Model):
    _name = 'sn.wsd.eip.clean.rule'
    _description = 'EIP Collection Limit Rule'
    _order = 'info_type_code, field_name, id'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    info_type_code = fields.Char(
        string='EIP Info Type Code', required=True, index=True,
        help='Interface the limit applies to.')
    field_name = fields.Selection(
        selection=LIMIT_FIELD_SELECTION,
        string='Value Field', required=True, index=True,
        help='Measured value column the limit bounds.')
    average_error_type = fields.Char(
        string='Error Type', default='', index=True,
        help='Type code the limit applies to (basic error detail D1..D4 '
             '/ H / A / B / C, AC analog IA.. II1). Empty = applies to '
             'every value of the field regardless of type.')
    lower_limit = fields.Float(
        string='Lower Limit', digits=(10, 3),
        help='Empty = no lower bound.')
    upper_limit = fields.Float(
        string='Upper Limit', digits=(10, 3),
        help='Empty = no upper bound.')
    active = fields.Boolean(default=True, index=True)

    _rule_uniq = models.Constraint(
        'unique(company_id, info_type_code, field_name, average_error_type)',
        'This interface value already has a limit rule for the type.',
    )

    @api.constrains('lower_limit', 'upper_limit')
    def _check_limits(self):
        for rule in self:
            if not rule.lower_limit and not rule.upper_limit:
                raise ValidationError(_(
                    'Set a lower limit, an upper limit, or both.'))
            if rule.lower_limit and rule.upper_limit \
                    and rule.lower_limit > rule.upper_limit:
                raise ValidationError(
                    _('The lower limit must not exceed the upper limit.'))

    def _eip_limit_problem(self, value):
        """Human-readable reason when ``value`` breaks this rule, else
        False. Zero readings are skipped: the required-field gate owns
        implausible zeros, limits judge real measurements."""
        if not value:
            return False
        if self.lower_limit and value < self.lower_limit:
            return '%s=%s < %s' % (
                self.field_name, value, self.lower_limit)
        if self.upper_limit and value > self.upper_limit:
            return '%s=%s > %s' % (
                self.field_name, value, self.upper_limit)
        return False
