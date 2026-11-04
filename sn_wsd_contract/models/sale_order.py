from datetime import datetime

from odoo import api, fields, models
from odoo.tools import formatLang
from odoo.tools.misc import NON_BREAKING_SPACE, format_amount, get_lang

from .contract_helper import cncurrency


def _default_contract_template(env):
    """Default sales contract template of the company."""
    return env['sn.contract.template']._get_default_template('sale')


class SaleOrder(models.Model):
    """Contract wording and contract data of the sale order.

    The fields and the formatting helpers mirror the purchase contract of the
    purchase module, so that both contracts print with the same conventions.
    """

    _inherit = 'sale.order'

    contract_template_id = fields.Many2one(
        'sn.contract.template', string='Contract Template',
        domain=[('contract_type', '=', 'sale')],
        default=lambda self: _default_contract_template(self.env),
        copy=True,
        help='Wording used by the sales contract of this order.')
    contract_number = fields.Char(
        string='Contract Number', copy=True,
        help='Contract number printed on the sales contract. Left empty, the '
             'order number is printed.')
    signing_date = fields.Date(
        string='Signing Date', copy=True,
        help='Date printed as the contract signing date.')
    signing_location = fields.Char(
        string='Signing Location', copy=True,
        default=lambda self: self.env.company.partner_id.city or '',
        help='Place printed as the contract signing place.')
    contract_attachment_ids = fields.Many2many(
        comodel_name='ir.attachment',
        relation='sale_order_contract_attachment_rel',
        column1='sale_order_id',
        column2='attachment_id',
        string='Contract Attachments', copy=True)
    has_contract_attachment = fields.Boolean(
        string='Contract Attached',
        compute='_compute_has_contract_attachment', store=True)

    amount_total_chinese = fields.Char(
        string='Total Amount in Chinese',
        compute='_compute_amount_total_chinese')
    amount_untaxed_chinese = fields.Char(
        string='Untaxed Amount in Chinese',
        compute='_compute_amount_total_chinese')
    amount_tax_chinese = fields.Char(
        string='Tax Amount in Chinese',
        compute='_compute_amount_total_chinese')

    @api.depends('contract_attachment_ids')
    def _compute_has_contract_attachment(self):
        for order in self:
            order.has_contract_attachment = bool(order.contract_attachment_ids)

    @api.depends('amount_total', 'amount_untaxed', 'amount_tax')
    def _compute_amount_total_chinese(self):
        for order in self:
            order.amount_total_chinese = cncurrency(order.amount_total)
            order.amount_untaxed_chinese = cncurrency(order.amount_untaxed)
            order.amount_tax_chinese = cncurrency(order.amount_tax)

    # ------------------------------------------------------------------
    # Formatting of the printed contract
    # ------------------------------------------------------------------
    @staticmethod
    def _strip_trailing_zeroes(value, decimal_point):
        """Remove insignificant decimal zeroes without changing integer zeroes."""
        decimal_position = value.rfind(decimal_point)
        if decimal_position == -1:
            return value
        return (value[:decimal_position]
                + value[decimal_position:].rstrip('0').rstrip(decimal_point))

    def _format_contract_quantity(self, value):
        """Format a quantity using the Product Unit precision."""
        precision = self.env['decimal.precision'].precision_get('Product Unit')
        formatted = formatLang(self.env, value, digits=precision)
        decimal_point = get_lang(self.env).decimal_point
        return self._strip_trailing_zeroes(formatted, decimal_point)

    def _format_contract_amount(self, value):
        """Format a detail amount using the currency precision."""
        currency = self.currency_id or self.company_id.currency_id
        return format_amount(self.env, value, currency, trailing_zeroes=False)

    def _format_contract_unit_price(self, value):
        """Format a unit price using the Product Price precision."""
        currency = self.currency_id or self.company_id.currency_id
        formatted = formatLang(self.env, value, dp='Product Price')
        formatted = self._strip_trailing_zeroes(
            formatted, get_lang(self.env).decimal_point)
        symbol = currency.symbol or ''
        if currency.position == 'before':
            return f'{symbol}{NON_BREAKING_SPACE}{formatted}'
        return f'{formatted}{NON_BREAKING_SPACE}{symbol}'

    def _format_contract_total(self, value):
        """Format a contract summary amount with exactly two decimals."""
        currency = self.currency_id or self.company_id.currency_id
        formatted = formatLang(self.env, value, digits=2)
        symbol = currency.symbol or ''
        if currency.position == 'before':
            return f'{symbol}{NON_BREAKING_SPACE}{formatted}'
        return f'{formatted}{NON_BREAKING_SPACE}{symbol}'

    def _format_contract_yuan(self, value):
        """Format an amount with a forced CNY symbol and two decimals."""
        formatted = formatLang(self.env, value, digits=2)
        return f'\u00a5{NON_BREAKING_SPACE}{formatted}'

    def _format_contract_date(self, value):
        """Return a contract date in YYYY/M/D format."""
        self.ensure_one()
        if not value:
            return ''
        if isinstance(value, datetime):
            value = value.date()
        return f'{value.year}/{value.month}/{value.day}'

    def _get_contract_address(self, partner):
        """Return a contract address from the largest region to the smallest."""
        self.ensure_one()
        partner = partner.commercial_partner_id or partner
        parts = (
            partner.state_id.name,
            partner.city,
            partner.street2,
            partner.street,
        )
        return ' '.join(part.strip() for part in parts if part and part.strip())

    def _contract_unit_price_tax_excluded(self, line):
        """Tax excluded unit price of an order line.

        Read from the untaxed subtotal rather than from the price of the line:
        a product priced tax included carries the tax in its price, and the
        contract prints both prices next to the tax rate.
        """
        if not line.product_uom_qty:
            return 0.0
        return line.price_subtotal / line.product_uom_qty

    def _contract_unit_price_tax_included(self, line):
        """Tax included unit price of an order line."""
        if not line.product_uom_qty:
            return 0.0
        return line.price_total / line.product_uom_qty

    def _contract_tax_rates(self, line):
        """Tax rates of a line, as printed in the tax rate column."""
        return ', '.join(
            formatLang(self.env, tax.amount, digits=2)
            for tax in line.tax_ids)

    def _contract_first_bank(self, partner):
        """Bank account of a party usable on the contract of this company."""
        self.ensure_one()
        partner = partner.commercial_partner_id or partner
        return partner.bank_ids.filtered_domain([
            '|', ('company_id', '=', False),
            ('company_id', '=', self.company_id.id),
        ])[:1]

    def _get_contract_lines(self):
        """Order lines reported on the contract: no section nor note line."""
        self.ensure_one()
        return self.order_line.filtered(
            lambda line: not line.display_type and line.product_uom_qty)

    def _get_contract_template(self):
        """Template of the order, falling back to the default one."""
        self.ensure_one()
        template = self.contract_template_id
        if not template:
            template = self.env['sn.contract.template']._get_default_template(
                'sale')
        return template

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_contract_preview(self):
        """Show the contract in the browser, before any PDF is produced.

        The layout configurator of the base module is skipped: the contract
        carries its own letterhead, so there is no external layout to choose.
        """
        self.ensure_one()
        return self.env.ref(
            'sn_wsd_contract.action_report_sale_contract_preview'
        ).report_action(self, config=False)

    def action_contract_pdf(self):
        """Download the contract as a PDF."""
        self.ensure_one()
        return self.env.ref(
            'sn_wsd_contract.action_report_sale_contract'
        ).report_action(self, config=False)

    def action_generate_contract_pdf(self):
        """Render the contract once and file the PDF on the order."""
        self.ensure_one()
        report = self.env.ref('sn_wsd_contract.action_report_sale_contract')
        content, _content_type = report._render_qweb_pdf(report, self.ids)
        name = 'Contract - %s.pdf' % (self.contract_number or self.name)
        attachment = self.env['ir.attachment'].create({
            'name': name.replace('/', '-'),
            'type': 'binary',
            'raw': content,
            'mimetype': 'application/pdf',
            'res_model': self._name,
            'res_id': self.id,
        })
        self.contract_attachment_ids = [(4, attachment.id)]
        return True
