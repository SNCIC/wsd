import logging

from odoo import api, fields, models
from odoo.tools import float_round

_logger = logging.getLogger(__name__)

# Where the unit cost of a material comes from. The value is carried with the
# cost so the screen can tell a real purchase price from a fallback.
PRICE_SOURCE_SELECTION = [
    ('purchase', 'Purchase Order'),
    ('pricelist', 'Vendor Pricelist'),
    ('standard', 'Standard Cost'),
    ('manufacture', 'Manufacturing Cost'),
]

# Last run of the scheduled refresh, kept in the system parameters so the job
# only looks at the purchase lines changed since then.
LAST_REFRESH_PARAM = 'sn_wsd_cost.last_purchase_price_refresh'

# Decimals kept on a stored unit price. The price is displayed with the Product
# Price precision, the extra digits only avoid losing cents on the UoM and
# currency conversions.
PRICE_DIGITS = 6


class ProductTemplate(models.Model):
    """Latest purchase price of the materials.

    The price is a fact read from the purchase orders, not a cost: it is stored
    per company the way the standard cost is, written when a purchase order is
    confirmed and by the scheduled refresh. Everything that needs a unit cost
    reads it through ``_sn_get_latest_cost``, which falls back on the vendor
    pricelist then on the standard cost so a material without purchase history
    still carries a cost.
    """

    _inherit = 'product.template'

    sn_latest_purchase_price = fields.Float(
        string='Latest Purchase Price',
        company_dependent=True,
        readonly=True,
        copy=False,
        min_display_digits='Product Price',
        groups='base.group_user',
        help='Tax included unit price of the latest confirmed purchase of this '
             'material, in the currency of the company and in the unit of '
             'measure of the product.',
    )
    sn_latest_purchase_date = fields.Date(
        string='Purchase Date',
        company_dependent=True,
        readonly=True,
        copy=False,
        groups='base.group_user',
        help='Confirmation date of the purchase order the latest price was '
             'read from.',
    )
    sn_latest_purchase_partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Cost Vendor',
        company_dependent=True,
        readonly=True,
        copy=False,
        groups='base.group_user',
        help='Vendor of the purchase order the latest price was read from.',
    )
    sn_latest_purchase_ref = fields.Char(
        string='Purchase Order',
        company_dependent=True,
        readonly=True,
        copy=False,
        groups='base.group_user',
        help='Reference of the purchase order the latest price was read from.',
    )
    sn_latest_purchase_source = fields.Selection(
        PRICE_SOURCE_SELECTION,
        string='Cost Source',
        company_dependent=True,
        readonly=True,
        copy=False,
        groups='base.group_user',
        help='Where the stored latest price was read from.',
    )

    # ------------------------------------------------------------------
    # Price resolution
    # ------------------------------------------------------------------
    def _sn_purchase_line_unit_cost(self, line, company):
        """Tax included unit cost of a purchase line, in company currency.

        The price is converted with the confirmation date of the order and
        expressed in the unit of measure of the purchased product so it can be
        compared with the standard cost of that product.
        """
        self.ensure_one()
        product = line.product_id
        price = line.price_unit_tax_included or line.price_unit
        if not price:
            return 0.0
        rate_date = line.date_approve or line.date_order \
            or fields.Datetime.now()
        price = line.currency_id._convert(
            price,
            company.currency_id,
            company,
            rate_date,
        )
        if line.product_uom_id and line.product_uom_id != product.uom_id:
            price = line.product_uom_id._compute_price(price, product.uom_id)
        return float_round(price, precision_digits=PRICE_DIGITS)

    def _sn_vendor_pricelist_entry(self):
        """Best valid vendor price of the product for the current company."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        company = self.env.company
        sellers = self.seller_ids.filtered(
            lambda seller: (not seller.company_id or seller.company_id == company)
            and (not seller.date_start or seller.date_start <= today)
            and (not seller.date_end or seller.date_end >= today)
        )
        return sellers.sorted(
            lambda seller: (seller.sequence, -seller.min_qty, -seller.id)
        )[:1]

    def _sn_get_latest_cost(self):
        """Unit cost of the product in company currency and product UoM.

        Returns the price, the date it applies from, the source it was read
        from, the vendor and the purchase order reference. The chain is the one
        of the ERP: latest purchase price, then vendor pricelist, then standard
        cost.
        """
        self.ensure_one()
        company = self.env.company
        if self.sn_latest_purchase_price:
            return {
                'price': self.sn_latest_purchase_price,
                'date': self.sn_latest_purchase_date,
                'source': 'purchase',
                'partner_id': self.sn_latest_purchase_partner_id,
                'reference': self.sn_latest_purchase_ref,
            }
        seller = self._sn_vendor_pricelist_entry()
        if seller:
            today = fields.Date.context_today(self)
            price = seller.currency_id._convert(
                seller.price, company.currency_id, company, today)
            if seller.discount:
                price *= 1 - seller.discount / 100.0
            if seller.product_uom_id and seller.product_uom_id != self.uom_id:
                price = seller.product_uom_id._compute_price(price, self.uom_id)
            return {
                'price': price,
                'date': seller.date_start,
                'source': 'pricelist',
                'partner_id': seller.partner_id,
                'reference': False,
            }
        variant = self.product_variant_id
        return {
            'price': variant.standard_price if variant else 0.0,
            'date': False,
            'source': 'standard',
            'partner_id': self.env['res.partner'],
            'reference': False,
        }

    def _sn_get_cost_in_uom(self, uom):
        """Latest cost of the product expressed in the given unit of measure."""
        self.ensure_one()
        cost = self._sn_get_latest_cost()
        cost['price'] = self.uom_id._compute_price(cost['price'], uom)
        return cost

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------
    def _sn_refresh_latest_purchase_price(self, company=None):
        """Write the latest confirmed purchase price of the templates.

        The company defaults to the current one; the purchase module passes the
        company of the order so a confirmation writes the right column.
        """
        company = company or self.env.company
        for template in self:
            line = self.env['purchase.order.line']
            for variant in template.product_variant_ids:
                line = variant._sn_latest_purchase_line(company)
                if line:
                    break
            if line:
                vals = {
                    'sn_latest_purchase_price':
                        template._sn_purchase_line_unit_cost(line, company),
                    'sn_latest_purchase_date':
                        line.date_approve and line.date_approve.date() or False,
                    'sn_latest_purchase_partner_id': line.order_id.partner_id.id,
                    'sn_latest_purchase_ref': line.order_id.name,
                    'sn_latest_purchase_source': 'purchase',
                }
            else:
                # No confirmed purchase any more (cancelled or deleted): the
                # stored price is dropped so the cost falls back on the chain.
                vals = {
                    'sn_latest_purchase_price': 0.0,
                    'sn_latest_purchase_date': False,
                    'sn_latest_purchase_partner_id': False,
                    'sn_latest_purchase_ref': False,
                    'sn_latest_purchase_source': False,
                }
            template.with_company(company).write(vals)
        return True

    def action_sn_refresh_latest_purchase_price(self):
        """Refresh the latest purchase price of the selected products."""
        self._sn_refresh_latest_purchase_price(self.env.company)
        return True

    # ------------------------------------------------------------------
    # Scheduled job
    # ------------------------------------------------------------------
    @api.model
    def _cron_sn_refresh_latest_purchase_price(self):
        """Refresh the materials whose purchase lines changed since last run."""
        params = self.env['ir.config_parameter'].sudo()
        last_run = params.get_param(LAST_REFRESH_PARAM)
        domain = [
            ('order_id.state', 'in', ('purchase', 'done')),
            ('order_id.date_approve', '!=', False),
            ('display_type', '=', False),
            ('product_qty', '>', 0),
        ]
        if last_run:
            domain.append(('write_date', '>=', last_run))
        lines = self.env['purchase.order.line'].search(domain)
        lines.product_id.product_tmpl_id._sn_refresh_latest_purchase_price()
        params.set_param(
            LAST_REFRESH_PARAM, fields.Datetime.to_string(fields.Datetime.now()))
        _logger.info(
            'Latest purchase price refreshed on %s product(s).',
            len(lines.product_id))
        return True


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _sn_latest_purchase_line(self, company):
        """Latest confirmed purchase line of the variant for the company.

        The orders are searched instead of the lines: the confirmation date is
        a field of the order and the ORM cannot sort the lines on it. The five
        last orders containing the product are read so an order whose line was
        left at a zero price does not hide the real last purchase.
        """
        self.ensure_one()
        orders = self.env['purchase.order'].search(
            [
                ('state', 'in', ('purchase', 'done')),
                ('company_id', '=', company.id),
                ('date_approve', '!=', False),
                ('order_line.product_id', '=', self.id),
                ('order_line.display_type', '=', False),
                ('order_line.product_qty', '>', 0),
            ],
            order='date_approve desc, id desc',
            limit=5,
        )
        product = self
        for order in orders:
            line = order.order_line.filtered(
                lambda order_line: not order_line.display_type
                and order_line.product_id == product
                and order_line.product_qty > 0
                and (order_line.price_unit_tax_included
                     or order_line.price_unit) > 0
            )[:1]
            if line:
                return line
        return self.env['purchase.order.line']

    def _sn_get_latest_cost(self):
        self.ensure_one()
        return self.product_tmpl_id._sn_get_latest_cost()

    def _sn_get_cost_in_uom(self, uom):
        self.ensure_one()
        return self.product_tmpl_id._sn_get_cost_in_uom(uom)

    def _sn_refresh_latest_purchase_price(self, company=None):
        company = company or self.env.company
        return self.product_tmpl_id._sn_refresh_latest_purchase_price(company)

    def action_sn_refresh_latest_purchase_price(self):
        return self.product_tmpl_id._sn_refresh_latest_purchase_price(
            self.env.company)
