from odoo import api, fields, models


class ProductionProcessDocType(models.Model):
    """Lightweight type list for craft documents maintained on the MO
    (default four, extensible without code)."""
    _name = 'production.process.doc.type'
    _description = 'Production Process Document Type'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True,
                       help='Stable key the device API checks against.')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True,
                                 default=lambda self: self.env.company)

    _code_uniq = models.Constraint(
        'unique(company_id, code)',
        'The process document type code must be unique per company.')


class ProductionProcessDoc(models.Model):
    """Craft documents maintained per MO + operation: a type and any number
    of document numbers (codes). The device API validates uploaded numbers
    against these lists."""
    _name = 'production.process.document'
    _description = 'Production Process Document'
    _order = 'production_id, id'

    production_id = fields.Many2one(
        'mrp.production', required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company,
        related='production_id.company_id', store=True, readonly=False)
    route_operation_code = fields.Char(
        required=True, index=True,
        help='Operation code of the MES-order route operation this list '
             'applies to.')
    type_id = fields.Many2one(
        'production.process.doc.type', required=True, index=True,
        domain="[('company_id', 'in', [company_id, False])]")
    code_ids = fields.One2many(
        'production.process.document.code', 'document_id', string='Codes')
    codes_display = fields.Char(compute='_compute_codes_display')
    note = fields.Text()

    @api.depends('code_ids.code')
    def _compute_codes_display(self):
        for doc in self:
            doc.codes_display = ', '.join(doc.code_ids.mapped('code'))

    _op_type_uniq = models.Constraint(
        'unique(production_id, route_operation_code, type_id)',
        'One document list per operation and type on a manufacturing order.')


class ProductionProcessDocCode(models.Model):
    _name = 'production.process.document.code'
    _description = 'Production Process Document Number'

    document_id = fields.Many2one(
        'production.process.document', required=True, ondelete='cascade')
    code = fields.Char(required=True)
    company_id = fields.Many2one(
        related='document_id.company_id', store=True)

    _code_uniq = models.Constraint(
        'unique(document_id, code)',
        'The document number must be unique in its list.')
