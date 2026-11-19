from odoo import api, fields, models

from .product_template import PRICE_SOURCE_SELECTION


class MrpBomLine(models.Model):
    """Cost of a component, read from the latest purchase price.

    The values are stored so the component lists can be sorted and grouped on
    the cost and on the purchase date. They follow the price of the material:
    a purchase confirmation writes the price on the product, which invalidates
    these fields through the dependencies below.

    The amounts are plain floats: a monetary field would read its currency
    through ``bom_id`` while the values are flushed, which fails once the BoM
    of a line has been deleted.
    """

    _inherit = 'mrp.bom.line'

    sn_unit_cost = fields.Float(
        string='Latest Unit Price',
        compute='_compute_sn_cost',
        store=True,
        min_display_digits='Product Price',
        help='Latest purchase price of the component, in the unit of measure '
             'of the component line and in the currency of the company.',
    )
    sn_cost_amount = fields.Float(
        string='Cost Amount',
        compute='_compute_sn_cost',
        store=True,
        min_display_digits='Product Price',
        help='Cost of the quantity consumed by this line, in the currency of '
             'the company.',
    )
    sn_cost_date = fields.Date(
        string='Purchase Date',
        compute='_compute_sn_cost',
        store=True,
        help='Confirmation date of the purchase the unit price comes from.',
    )
    sn_cost_source = fields.Selection(
        PRICE_SOURCE_SELECTION,
        string='Cost Source',
        compute='_compute_sn_cost',
        store=True,
        help='Where the unit price comes from: a purchase order, the vendor '
             'pricelist or the standard cost of the material.',
    )
    sn_cost_partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Cost Vendor',
        compute='_compute_sn_cost',
        store=True,
        help='Vendor the unit price was purchased from.',
    )

    @api.depends(
        'product_id',
        'product_qty',
        'product_uom_id',
        'bom_id.company_id',
        'product_id.standard_price',
        'product_id.product_tmpl_id.sn_latest_purchase_price',
        'product_id.product_tmpl_id.sn_latest_purchase_date',
        'product_id.product_tmpl_id.sn_latest_purchase_partner_id',
        'product_id.product_tmpl_id.sn_latest_purchase_source',
        'product_id.product_tmpl_id.seller_ids.price',
        'product_id.product_tmpl_id.seller_ids.discount',
        'product_id.product_tmpl_id.seller_ids.date_start',
        'product_id.product_tmpl_id.seller_ids.date_end',
    )
    def _compute_sn_cost(self):
        # A pending computation may be flushed after the lines were deleted
        # (the deletion of a BoM drops them): the existing subset is read so
        # the compute never walks up to a parent that is already gone.
        for line in self.exists():
            line.sn_unit_cost = 0.0
            line.sn_cost_amount = 0.0
            line.sn_cost_date = False
            line.sn_cost_source = False
            line.sn_cost_partner_id = False
            if not line.product_id:
                continue
            company = line.bom_id.company_id or self.env.company
            uom = line.product_uom_id or line.product_id.uom_id
            product = line.product_id.with_company(company)
            cost = product._sn_get_cost_in_uom(uom)
            line.sn_unit_cost = cost['price']
            line.sn_cost_amount = company.currency_id.round(
                cost['price'] * line.product_qty)
            line.sn_cost_date = cost['date']
            line.sn_cost_source = cost['source']
            line.sn_cost_partner_id = cost['partner_id']
