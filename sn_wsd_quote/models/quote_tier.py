from odoo import api, fields, models


class SnWsdQuoteTier(models.Model):
    """Quoted price for another quantity of the same estimate.

    The variable costs do not change with the quantity, the one-off costs do:
    the tier shows the unit cost and the price of the same worksheet for a
    smaller or a larger order.
    """

    _name = 'sn.wsd.quote.tier'
    _description = 'Quotation Estimate Tier'
    _order = 'quantity, id'

    quote_id = fields.Many2one(
        comodel_name='sn.wsd.quote',
        string='Quotation Estimate',
        required=True,
        ondelete='cascade',
        index=True,
    )
    quantity = fields.Float(
        string='Quantity',
        default=1.0,
        digits='Product Unit',
        required=True,
    )
    unit_cost = fields.Monetary(
        string='Unit Cost',
        compute='_compute_tier',
        store=True,
        currency_field='currency_id',
    )
    price_unit = fields.Monetary(
        string='Unit Price',
        compute='_compute_tier',
        store=True,
        currency_field='currency_id',
    )
    margin_percent = fields.Float(
        string='Margin (%)',
        compute='_compute_tier',
        store=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='quote_id.currency_id',
        store=True,
        readonly=True,
    )

    @api.depends(
        'quantity',
        'quote_id.material_cost',
        'quote_id.operation_cost',
        'quote_id.expense_cost',
        'quote_id.overhead_cost',
        'quote_id.management_cost',
        'quote_id.fixed_cost',
        'quote_id.markup_percent',
        'quote_id.currency_id',
    )
    def _compute_tier(self):
        for tier in self:
            quote = tier.quote_id
            variable = (
                quote.material_cost
                + quote.operation_cost
                + quote.expense_cost
                + quote.overhead_cost
                + quote.management_cost
            )
            unit_cost = variable
            if tier.quantity:
                unit_cost += quote.fixed_cost / tier.quantity
            price = unit_cost * (1 + (quote.markup_percent or 0.0) / 100.0)
            if quote.currency_id:
                price = quote.currency_id.round(price)
            tier.unit_cost = unit_cost
            tier.price_unit = price
            tier.margin_percent = (
                (price - unit_cost) / price * 100.0 if price else 0.0)
