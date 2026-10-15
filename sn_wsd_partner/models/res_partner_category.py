from odoo import fields, models


class ResPartnerCategory(models.Model):
    """Contact tags double as supplier groups: the account numbers its
    supplier groups with a two-digit code (01, 02, 03, 05 ... 99) and the
    supplier code is that number plus a per-group serial."""

    _inherit = 'res.partner.category'

    code = fields.Char(
        string='Code', copy=False,
        help='Code prefixed to the automatically generated supplier code, '
             'e.g. 01 for the electronic components group. Fill it only on '
             'the groups used as supplier groups; each code may exist once.')

    _code_unique = models.Constraint(
        'unique(code)',
        'The group code must be unique.',
    )
