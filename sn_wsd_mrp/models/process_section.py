from odoo import fields, models


class SnWsdProcessSection(models.Model):
    """Lightweight process-section list for operations and route section
    statistics (default seven, extensible on the page without code)."""
    _name = 'sn.wsd.process.section'
    _description = 'Process Section'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True,
                       help='Stable key legacy data maps onto.')
    sequence = fields.Integer(default=50)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company)

    _code_uniq = models.Constraint(
        'unique(company_id, code)',
        'The process section code must be unique per company.')
