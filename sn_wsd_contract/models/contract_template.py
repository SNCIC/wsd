from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SnContractTemplate(models.Model):
    """Contract template: the wording of a contract, the sheet it prints on.

    The item table and the party block carry data of the document and stay in
    the report template; everything the parties agree word by word lives here,
    so a lawyer changes a clause in the form instead of an XML file.
    """

    _name = 'sn.contract.template'
    _description = 'Contract Template'
    _order = 'contract_type, sequence, id'

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(
        string='Code', index=True,
        help='Short code of the template, unique per contract type.')
    contract_type = fields.Selection(
        [('sale', 'Sales Contract'),
         ('purchase', 'Purchase Contract')],
        string='Contract Type', required=True, default='sale', index=True)
    active = fields.Boolean(default=True)
    is_default = fields.Boolean(
        string='Default Template',
        help='Template brought in on a new document of this contract type.')
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        'res.company', string='Company', index=True, ondelete='cascade',
        default=lambda self: self.env.company,
        help='Leave empty to share the template with every company.')

    title = fields.Char(
        string='Document Title', translate=True,
        help='Title printed in the head of the contract.')
    intro = fields.Text(
        string='Introduction', translate=True,
        help='Paragraph printed above the item table, after the party block.')
    clause_ids = fields.One2many(
        'sn.contract.template.clause', 'template_id', string='Clauses',
        copy=True)
    clause_count = fields.Integer(compute='_compute_clause_count')

    show_tax_rate = fields.Boolean(
        string='Print the Tax Rate Column', default=True)
    show_tax_excluded_price = fields.Boolean(
        string='Print the Untaxed Unit Price Column', default=True)
    paperformat_id = fields.Many2one(
        'report.paperformat', string='Paper Format',
        help='Paper of the contract. The report falls back to its own A4 '
             'format when empty.')

    @api.depends('clause_ids')
    def _compute_clause_count(self):
        for template in self:
            template.clause_count = len(template.clause_ids)

    @api.constrains('code', 'contract_type')
    def _check_code_unique(self):
        for template in self:
            if not template.code:
                continue
            duplicate = self.search_count([
                ('id', '!=', template.id),
                ('contract_type', '=', template.contract_type),
                ('code', '=', template.code),
            ])
            if duplicate:
                raise ValidationError(_(
                    'The contract template code "%(code)s" is already used '
                    'for this contract type.',
                    code=template.code))

    @api.model
    def _get_default_template(self, contract_type):
        """Default template of a contract type: company first, then global."""
        template = self.search([
            ('contract_type', '=', contract_type),
            ('is_default', '=', True),
            ('company_id', 'in', [self.env.company.id, False]),
        ], order='company_id desc, sequence, id', limit=1)
        if template:
            return template
        return self.search([
            ('contract_type', '=', contract_type),
            ('company_id', 'in', [self.env.company.id, False]),
        ], order='company_id desc, sequence, id', limit=1)


class SnContractTemplateClause(models.Model):
    """One numbered heading of a contract template with its wording.

    The number is part of the heading on purpose: a clause is inserted,
    removed or renumbered by editing its heading, which is what a contract
    template asks for — no counter to keep in sync with the printed paper.
    """

    _name = 'sn.contract.template.clause'
    _description = 'Contract Template Clause'
    _order = 'sequence, id'

    template_id = fields.Many2one(
        'sn.contract.template', string='Template', required=True,
        ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(
        string='Heading', required=True, translate=True,
        help='Heading printed above the wording, number included.')
    content = fields.Text(
        string='Content', translate=True,
        help='Wording of the clause. Left empty, the contract prints the '
             'heading only, which leaves room for a hand-written clause.')
