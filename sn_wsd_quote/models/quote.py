from datetime import timedelta

from odoo import api, fields, models


class SnWsdQuote(models.Model):
    """Quotation estimate of a product.

    The worksheet is independent from the sales flow: it computes what one unit
    of the product costs at the latest purchase prices of its components and at
    the piece rates of its process route, adds the indirect and one-off costs,
    and derives the quoted price from a markup. Nothing is written on the
    product cost nor on a sales order: the quote is a simulation with its own
    frozen snapshot of the prices it was built on.
    """

    _name = 'sn.wsd.quote'
    _description = 'Quotation Estimate'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Reference',
        default='/',
        copy=False,
        readonly=True,
        required=True,
        index=True,
    )
    revision = fields.Integer(
        string='Revision',
        default=1,
        copy=False,
        readonly=True,
    )
    state = fields.Selection(
        [('draft', 'Draft'),
         ('confirmed', 'Confirmed'),
         ('sent', 'Sent'),
         ('won', 'Won'),
         ('lost', 'Lost')],
        string='Status',
        default='draft',
        required=True,
        copy=False,
        tracking=True,
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Customer',
        required=True,
        tracking=True,
        check_company=True,
    )
    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Product',
        required=True,
        tracking=True,
        check_company=True,
    )
    product_code = fields.Char(
        string='Product Code',
        related='product_id.default_code',
    )
    material_specification = fields.Char(
        string='Specification',
        related='product_id.material_specification',
    )
    bom_id = fields.Many2one(
        comodel_name='mrp.bom',
        string='Bill of Materials',
        check_company=True,
    )
    route_id = fields.Many2one(
        comodel_name='sn.wsd.process.route',
        string='Process Route',
        check_company=True,
    )
    quantity = fields.Float(
        string='Quantity',
        default=1.0,
        digits='Product Unit',
        required=True,
        help='Quantity quoted. The one-off costs are spread over it, so it '
             'drives the unit cost of the worksheet.',
    )
    uom_id = fields.Many2one(
        comodel_name='uom.uom',
        string='Unit',
        compute='_compute_uom_id',
        store=True,
        readonly=False,
        precompute=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    date = fields.Date(
        string='Date',
        default=fields.Date.context_today,
        required=True,
        copy=False,
    )
    validity_date = fields.Date(
        string='Valid Until',
        default=lambda self: fields.Date.context_today(self) + timedelta(days=30),
        help='Date the quoted price stops applying.',
    )
    user_id = fields.Many2one(
        comodel_name='res.users',
        string='Salesperson',
        default=lambda self: self.env.user,
        tracking=True,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )
    note = fields.Text(string='Internal Note')

    line_ids = fields.One2many(
        comodel_name='sn.wsd.quote.line',
        inverse_name='quote_id',
        string='Cost Lines',
        copy=True,
    )
    tier_ids = fields.One2many(
        comodel_name='sn.wsd.quote.tier',
        inverse_name='quote_id',
        string='Quantity Tiers',
        copy=True,
    )

    # ------------------------------------------------------------------
    # Costs (per one unit of the quoted product)
    # ------------------------------------------------------------------
    material_cost = fields.Monetary(
        string='Material Cost',
        compute='_compute_costs',
        store=True,
        currency_field='currency_id',
    )
    operation_cost = fields.Monetary(
        string='Operation Cost',
        compute='_compute_costs',
        store=True,
        currency_field='currency_id',
    )
    expense_cost = fields.Monetary(
        string='Expense per Unit',
        compute='_compute_costs',
        store=True,
        currency_field='currency_id',
    )
    fixed_cost = fields.Monetary(
        string='One-off Cost',
        compute='_compute_costs',
        store=True,
        currency_field='currency_id',
        help='Tooling, certification, packing design: costs invoiced once for '
             'the whole order, spread over the quoted quantity.',
    )
    overhead_percent = fields.Float(
        string='Overhead Rate (%)',
        default=0.0,
        help='Manufacturing overhead, applied to the material and operation '
             'costs.',
    )
    management_percent = fields.Float(
        string='Management Rate (%)',
        default=0.0,
        help='Management and finance expenses, applied to the material, '
             'operation and overhead costs.',
    )
    overhead_cost = fields.Monetary(
        string='Overhead',
        compute='_compute_costs',
        store=True,
        currency_field='currency_id',
    )
    management_cost = fields.Monetary(
        string='Management',
        compute='_compute_costs',
        store=True,
        currency_field='currency_id',
    )
    unit_cost = fields.Monetary(
        string='Unit Cost',
        compute='_compute_costs',
        store=True,
        currency_field='currency_id',
        help='Cost of one unit of the quoted product, one-off costs spread '
             'over the quoted quantity.',
    )

    # ------------------------------------------------------------------
    # Quoted price
    # ------------------------------------------------------------------
    markup_percent = fields.Float(
        string='Markup (%)',
        default=20.0,
        help='Percentage added to the unit cost to obtain the quoted price.',
    )
    price_unit = fields.Monetary(
        string='Unit Price',
        compute='_compute_price',
        inverse='_inverse_price_unit',
        store=True,
        readonly=False,
        currency_field='currency_id',
        help='Quoted unit price. Writing it back-computes the markup, so the '
             'price can be entered directly when the market sets it.',
    )
    amount_total = fields.Monetary(
        string='Quoted Amount',
        compute='_compute_margin',
        store=True,
        currency_field='currency_id',
    )
    margin_amount = fields.Monetary(
        string='Margin',
        compute='_compute_margin',
        store=True,
        currency_field='currency_id',
    )
    margin_percent = fields.Float(
        string='Margin (%)',
        compute='_compute_margin',
        store=True,
    )

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------
    @api.depends('product_id')
    def _compute_uom_id(self):
        for quote in self:
            if quote.product_id.uom_id:
                quote.uom_id = quote.product_id.uom_id

    @api.depends(
        'line_ids.amount',
        'line_ids.line_type',
        'line_ids.is_fixed',
        'quantity',
        'overhead_percent',
        'management_percent',
    )
    def _compute_costs(self):
        for quote in self:
            material = sum(
                quote.line_ids.filtered(
                    lambda line: line.line_type == 'material').mapped('amount'))
            operation = sum(
                quote.line_ids.filtered(
                    lambda line: line.line_type == 'operation').mapped('amount'))
            expenses = quote.line_ids.filtered(
                lambda line: line.line_type == 'expense')
            expense = sum(expenses.filtered(
                lambda line: not line.is_fixed).mapped('amount'))
            fixed = sum(expenses.filtered(
                lambda line: line.is_fixed).mapped('amount'))
            overhead = (material + operation) * (quote.overhead_percent or 0.0) / 100.0
            management = (material + operation + overhead) \
                * (quote.management_percent or 0.0) / 100.0
            unit = material + operation + expense + overhead + management
            if quote.quantity:
                unit += fixed / quote.quantity
            quote.material_cost = material
            quote.operation_cost = operation
            quote.expense_cost = expense
            quote.fixed_cost = fixed
            quote.overhead_cost = overhead
            quote.management_cost = management
            quote.unit_cost = unit

    @api.depends('unit_cost', 'markup_percent', 'currency_id')
    def _compute_price(self):
        for quote in self:
            price = quote.unit_cost * (1 + (quote.markup_percent or 0.0) / 100.0)
            quote.price_unit = quote.currency_id.round(price) \
                if quote.currency_id else price

    def _inverse_price_unit(self):
        for quote in self:
            if quote.unit_cost:
                quote.markup_percent = (
                    quote.price_unit / quote.unit_cost - 1) * 100.0
            else:
                quote.markup_percent = 0.0

    @api.depends('price_unit', 'unit_cost', 'quantity')
    def _compute_margin(self):
        for quote in self:
            quote.amount_total = quote.price_unit * quote.quantity
            quote.margin_amount = quote.amount_total \
                - quote.unit_cost * quote.quantity
            quote.margin_percent = (
                quote.margin_amount / quote.amount_total * 100.0
                if quote.amount_total else 0.0
            )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'sn.wsd.quote') or '/'
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_generate_costs(self):
        """Open the wizard filling the cost lines from the BoM."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Generate Cost from Bill of Materials',
            'res_model': 'sn.wsd.quote.generate',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_quote_id': self.id,
                'default_bom_id': self.bom_id.id,
                'default_route_id': self.route_id.id,
            },
        }

    def action_confirm(self):
        self.write({'state': 'confirmed'})
        return True

    def action_send(self):
        self.write({'state': 'sent'})
        return True

    def action_won(self):
        self.write({'state': 'won'})
        return True

    def action_lost(self):
        self.write({'state': 'lost'})
        return True

    def action_reset(self):
        self.write({'state': 'draft'})
        return True

    def action_new_revision(self):
        """Duplicate the quote as the next revision, back in draft."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Quotation Estimate',
            'res_model': 'sn.wsd.quote',
            'res_id': self.copy({
                'revision': self.revision + 1,
                'state': 'draft',
            }).id,
            'view_mode': 'form',
            'target': 'current',
        }
