from odoo import fields, models


class SnWsdExceptionReason(models.Model):
    _name = 'sn.wsd.exception.reason'
    _description = 'SN WSD Exception Reason'
    _order = 'sequence, id'
    _check_company_auto = True

    name = fields.Char(string='Exception Reason', required=True, translate=True)
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
    description = fields.Text(string='Description')

    _name_company_uniq = models.Constraint(
        'unique(company_id, name)',
        'The exception reason name must be unique per company.',
    )
