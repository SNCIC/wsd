from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.sn_wsd_cost.models.product_template import PRICE_SOURCE_SELECTION


class SnWsdQuoteLine(models.Model):
    """One cost of the quotation estimate, per one unit of the product.

    A material line carries the quantity consumed by one unit of the product,
    its loss rate and the unit price read from the latest purchase price. An
    operation line carries the piece rate of the operation. An expense line is
    either a cost per unit or a one-off cost of the whole order, which is then
    spread over the quoted quantity.
    """

    _name = 'sn.wsd.quote.line'
    _description = 'Quotation Estimate Line'
    _order = 'quote_id, sequence, id'
    _check_company_auto = True

    quote_id = fields.Many2one(
        comodel_name='sn.wsd.quote',
        string='Quotation Estimate',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(string='Sequence', default=10)
    line_type = fields.Selection(
        [('material', 'Material'),
         ('operation', 'Operation'),
         ('expense', 'Expense')],
        string='Type',
        default='material',
        required=True,
    )
    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Material',
        check_company=True,
    )
    product_code = fields.Char(
        string='Material Code',
        related='product_id.default_code',
    )
    material_specification = fields.Char(
        string='Specification',
        related='product_id.material_specification',
    )
    operation_id = fields.Many2one(
        comodel_name='sn.wsd.operation',
        string='Operation',
        check_company=True,
    )
    name = fields.Char(
        string='Description',
        help='Label printed on the cost sheet. Filled from the material or the '
             'operation, free text for an expense.',
    )
    uom_id = fields.Many2one(
        comodel_name='uom.uom',
        string='Unit',
    )
    quantity = fields.Float(
        string='Quantity',
        default=1.0,
        digits='Product Unit',
        help='Quantity consumed by one unit of the quoted product, in the unit '
             'of the line.',
    )
    loss_percent = fields.Float(
        string='Loss (%)',
        default=0.0,
        help='Scrap rate of the material, applied on top of the quantity.',
    )
    unit_price = fields.Monetary(
        string='Unit Price',
        currency_field='currency_id',
    )
    price_date = fields.Date(
        string='Price Date',
        help='Confirmation date of the purchase the material price comes from.',
    )
    price_source = fields.Selection(
        PRICE_SOURCE_SELECTION,
        string='Price Source',
    )
    is_fixed = fields.Boolean(
        string='One-off',
        help='Expense invoiced once for the whole order (tooling, '
             'certification, freight): the amount is the total, not a cost per '
             'unit.',
    )
    amount = fields.Monetary(
        string='Amount',
        compute='_compute_amount',
        store=True,
        currency_field='currency_id',
        help='Cost per one unit of the quoted product, or the total for a '
             'one-off expense.',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='quote_id.currency_id',
        store=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        related='quote_id.company_id',
        store=True,
        readonly=True,
    )
    price_missing = fields.Boolean(
        string='Price Missing',
        compute='_compute_price_missing',
        store=True,
        help='Set when a material or an operation has no price at all: the '
             'estimate understates the cost and the line has to be priced by '
             'hand.',
    )

    @api.depends('line_type', 'unit_price')
    def _compute_price_missing(self):
        for line in self:
            line.price_missing = line.line_type != 'expense' and not line.unit_price

    @api.depends('line_type', 'quantity', 'loss_percent', 'unit_price', 'is_fixed')
    def _compute_amount(self):
        for line in self:
            price = line.unit_price or 0.0
            if line.is_fixed and line.line_type == 'expense':
                line.amount = price
                continue
            quantity = line.quantity or 0.0
            if line.line_type == 'material':
                quantity *= 1 + (line.loss_percent or 0.0) / 100.0
            line.amount = quantity * price

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for line in self:
            if line.product_id:
                line.uom_id = line.product_id.uom_id
                if not line.name:
                    line.name = line.product_id.display_name

    @api.constrains('line_type', 'product_id', 'operation_id')
    def _check_line_target(self):
        for line in self:
            if line.line_type == 'material' and not line.product_id:
                raise ValidationError(
                    'A material line requires a material.')
            if line.line_type == 'operation' and not line.operation_id:
                raise ValidationError(
                    'An operation line requires an operation.')
