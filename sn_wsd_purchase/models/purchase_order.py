from decimal import Decimal
from datetime import datetime

from odoo import api, fields, models
from odoo.tools import formatLang
from odoo.tools.misc import NON_BREAKING_SPACE, format_amount, get_lang


def cncurrency(value, capital=True, prefix=False, classical=None):
    """Convert a decimal amount to Chinese currency wording."""
    if classical is None:
        classical = True if capital else False

    prefix = '人民币' if prefix is True else ''
    dunit = ('角', '分')
    if capital:
        num = ('零', '壹', '贰', '叁', '肆', '伍', '陆', '柒', '捌', '玖')
        iunit = [
            None, '拾', '佰', '仟', '万', '拾', '佰', '仟',
            '亿', '拾', '佰', '仟', '万', '拾', '佰', '仟',
        ]
    else:
        num = ('〇', '一', '二', '三', '四', '五', '六', '七', '八', '九')
        iunit = [
            None, '十', '百', '千', '万', '十', '百', '千',
            '亿', '十', '百', '千', '万', '十', '百', '千',
        ]
    iunit[0] = '元' if classical else '圆'

    value = Decimal(str(value)).quantize(Decimal('0.01'))

    if value < 0:
        prefix += '负'
        value = -value

    amount_text = str(value)
    if len(amount_text) > 19:
        raise ValueError('Amount is too large to convert to Chinese currency wording.')
    integer_text, decimal_text = amount_text.split('.')
    integer_text = integer_text[::-1]
    result = []

    if value == 0:
        return prefix + num[0] + iunit[0] + '整'

    has_zero = decimal_text == '00'
    if decimal_text[1] != '0':
        result.extend((dunit[1], num[int(decimal_text[1])]))
    else:
        result.append('整')
    if decimal_text[0] != '0':
        result.extend((dunit[0], num[int(decimal_text[0])]))

    if integer_text == '0':
        if has_zero:
            result.pop()
        result.append(prefix)
        result.reverse()
        return ''.join(result)

    for index, digit in enumerate(integer_text):
        digit = int(digit)
        if index % 4 == 0:
            if index == 8 and result[-1] == iunit[4]:
                result.pop()
            result.append(iunit[index])
            if digit:
                result.append(num[digit])
                has_zero = False
        elif digit:
            result.extend((iunit[index], num[digit]))
            has_zero = False
        elif not has_zero:
            result.append(num[0])
            has_zero = True

    result.append(prefix)
    result.reverse()
    return ''.join(result)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    @staticmethod
    def _strip_trailing_zeroes(value, decimal_point):
        """Remove insignificant decimal zeroes without changing integer zeroes."""
        decimal_position = value.rfind(decimal_point)
        if decimal_position == -1:
            return value
        return value[:decimal_position] + value[decimal_position:].rstrip('0').rstrip(decimal_point)

    def _format_contract_quantity(self, value):
        """Format a quantity using the Product Unit precision without trailing zeroes."""
        precision = self.env['decimal.precision'].precision_get('Product Unit')
        formatted = formatLang(self.env, value, digits=precision)
        decimal_point = get_lang(self.env).decimal_point
        return self._strip_trailing_zeroes(formatted, decimal_point)

    def _format_contract_amount(self, value):
        """Format a detail amount using the currency precision without trailing zeroes."""
        currency = self.currency_id or self.company_id.currency_id
        return format_amount(self.env, value, currency, trailing_zeroes=False)

    def _format_contract_unit_price(self, value):
        """Format a unit price using Product Price precision without trailing zeroes."""
        currency = self.currency_id or self.company_id.currency_id
        formatted = formatLang(self.env, value, dp='Product Price')
        formatted = self._strip_trailing_zeroes(formatted, get_lang(self.env).decimal_point)
        symbol = currency.symbol or ''
        if currency.position == 'before':
            return f'{symbol}{NON_BREAKING_SPACE}{formatted}'
        return f'{formatted}{NON_BREAKING_SPACE}{symbol}'

    def _format_contract_total(self, value):
        """Format a contract summary amount with exactly two decimal places."""
        currency = self.currency_id or self.company_id.currency_id
        formatted = formatLang(self.env, value, digits=2)
        symbol = currency.symbol or ''
        if currency.position == 'before':
            return f'{symbol}{NON_BREAKING_SPACE}{formatted}'
        return f'{formatted}{NON_BREAKING_SPACE}{symbol}'

    def _get_contract_address(self, partner):
        """Return a contract address from the largest region to the smallest."""
        self.ensure_one()
        address_parts = (
            partner.state_id.name,
            partner.city,
            partner.street2,
            partner.street,
        )
        return ' '.join(part.strip() for part in address_parts if part and part.strip())

    def _format_contract_date(self, value):
        """Return a contract date in YYYY/M/D format."""
        self.ensure_one()
        if not value:
            return ''
        if isinstance(value, datetime):
            value = value.date()
        return f'{value.year}/{value.month}/{value.day}'

    amount_total_chinese = fields.Char(
        string='Total Amount in Chinese',
        compute='_compute_amount_total_chinese',
    )
    amount_untaxed_chinese = fields.Char(
        string='Untaxed Amount in Chinese',
        compute='_compute_amount_total_chinese',
    )

    contract_number = fields.Char(
        string='Contract Number',
        copy=True,
        help='Contract number printed on the purchase contract.',
    )
    signing_date = fields.Date(
        string='Signing Date',
        copy=True,
        help='Date printed as the contract signing date.',
    )
    signing_location = fields.Char(
        string='Signing Location',
        copy=True,
    )
    buyer_bank_id = fields.Many2one(
        comodel_name='res.partner.bank',
        string='Buyer Bank Account',
        copy=True,
        domain="[('partner_id', '=', company_id.partner_id), '|', "
               "('company_id', '=', False), ('company_id', '=', company_id)]",
        help='Bank account printed for the buyer on the purchase contract.',
    )
    supplier_bank_id = fields.Many2one(
        comodel_name='res.partner.bank',
        string='Supplier Bank Account',
        copy=True,
        domain="[('partner_id', '=', partner_id), '|', "
               "('company_id', '=', False), ('company_id', '=', company_id)]",
        help='Bank account printed for the supplier on the purchase contract.',
    )
    delivery_date_text = fields.Char(
        string='Delivery Date Description',
        copy=True,
    )
    delivery_location = fields.Char(
        string='Delivery Location',
        copy=True,
    )
    technical_requirements = fields.Html(
        string='Technical Requirements',
        copy=True,
    )
    acceptance_terms = fields.Html(
        string='Acceptance Terms',
        copy=True,
    )
    payment_terms_text = fields.Html(
        string='Payment Terms Description',
        copy=True,
    )
    liability_terms = fields.Html(
        string='Liability Terms',
        copy=True,
    )
    buyer_agent = fields.Char(
        string='Buyer Agent',
        copy=True,
    )
    supplier_agent = fields.Char(
        string='Supplier Agent',
        copy=True,
    )

    @api.depends('amount_total', 'amount_untaxed')
    def _compute_amount_total_chinese(self):
        for order in self:
            order.amount_total_chinese = cncurrency(order.amount_total, prefix=True)
            order.amount_untaxed_chinese = cncurrency(order.amount_untaxed, prefix=True)


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    price_unit_tax_included = fields.Float(
        string='Unit Price Tax Included',
        min_display_digits='Product Price',
    )
    price_unit_tax_excluded = fields.Float(
        string='Untaxed Unit Price',
        min_display_digits='Product Price',
    )

    def _get_tax_details(self, price_unit, special_mode=False):
        self.ensure_one()
        if not self.tax_ids:
            return {
                'total_excluded': price_unit,
                'total_included': price_unit,
            }
        return self.tax_ids._get_tax_details(
            price_unit,
            1.0,
            precision_rounding=self.currency_id.rounding,
            rounding_method='round_globally',
            product=self.product_id,
            product_uom=self.product_uom_id,
            special_mode=special_mode,
        )

    def _get_unit_price_values(self, price_unit):
        self.ensure_one()
        tax_details = self._get_tax_details(price_unit)
        return tax_details['total_included'], tax_details['total_excluded']

    def _get_display_values_from_price_unit(self, price_unit):
        self.ensure_one()
        return self._get_unit_price_values(price_unit)

    def _get_price_unit_from_tax_included(self, price_unit_tax_included):
        self.ensure_one()
        if self.order_id.company_price_include == 'tax_included':
            return price_unit_tax_included
        return self._get_tax_details(
            price_unit_tax_included,
            special_mode='total_included',
        )['total_excluded']

    def _get_price_unit_from_tax_excluded(self, price_unit_tax_excluded):
        self.ensure_one()
        if self.order_id.company_price_include == 'tax_excluded':
            return price_unit_tax_excluded
        return self._get_tax_details(
            price_unit_tax_excluded,
            special_mode='total_excluded',
        )['total_included']

    @api.onchange('price_unit', 'tax_ids', 'product_id', 'product_uom_id', 'currency_id')
    def _onchange_price_unit_tax_values(self):
        for line in self:
            line.price_unit_tax_included, line.price_unit_tax_excluded = line._get_display_values_from_price_unit(
                line.price_unit
            )

    @api.onchange('price_unit_tax_included')
    def _onchange_price_unit_tax_included(self):
        for line in self:
            line.price_unit = line._get_price_unit_from_tax_included(line.price_unit_tax_included)
            line.price_unit_tax_included, line.price_unit_tax_excluded = line._get_display_values_from_price_unit(
                line.price_unit
            )

    @api.onchange('price_unit_tax_excluded')
    def _onchange_price_unit_tax_excluded(self):
        for line in self:
            line.price_unit = line._get_price_unit_from_tax_excluded(line.price_unit_tax_excluded)
            line.price_unit_tax_included, line.price_unit_tax_excluded = line._get_display_values_from_price_unit(
                line.price_unit
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            line = self.new(vals)
            if 'price_unit_tax_included' in vals or 'price_unit_tax_excluded' in vals:
                if 'price_unit_tax_included' in vals and 'price_unit_tax_excluded' not in vals:
                    vals['price_unit'] = line._get_price_unit_from_tax_included(
                        vals['price_unit_tax_included']
                    )
                elif 'price_unit_tax_excluded' in vals and 'price_unit_tax_included' not in vals:
                    vals['price_unit'] = line._get_price_unit_from_tax_excluded(
                        vals['price_unit_tax_excluded']
                    )
                elif line.order_id.company_price_include == 'tax_included':
                    vals['price_unit'] = line._get_price_unit_from_tax_included(
                        vals['price_unit_tax_included']
                    )
                else:
                    vals['price_unit'] = line._get_price_unit_from_tax_excluded(
                        vals['price_unit_tax_excluded']
                    )
                included, excluded = line._get_display_values_from_price_unit(vals['price_unit'])
                vals.update(
                    price_unit_tax_included=included,
                    price_unit_tax_excluded=excluded,
                )
        lines = super().create(vals_list)
        lines._sync_display_price_values()
        return lines

    def write(self, vals):
        display_fields = {'price_unit_tax_included', 'price_unit_tax_excluded'}
        if self.env.context.get('skip_wsd_price_sync'):
            return super().write(vals)
        if not (display_fields & vals.keys()):
            result = super().write(vals)
            if result and ('price_unit' in vals or {'tax_ids', 'product_id', 'product_uom_id', 'currency_id'} & vals.keys()):
                self._sync_display_price_values()
            return result
        for line in self:
            line_vals = dict(vals)
            included = vals.get('price_unit_tax_included')
            excluded = vals.get('price_unit_tax_excluded')
            if included is not None and excluded is None:
                line_vals['price_unit'] = line._get_price_unit_from_tax_included(included)
            elif excluded is not None and included is None:
                line_vals['price_unit'] = line._get_price_unit_from_tax_excluded(excluded)
            elif line.order_id.company_price_include == 'tax_included':
                line_vals['price_unit'] = line._get_price_unit_from_tax_included(included)
            else:
                line_vals['price_unit'] = line._get_price_unit_from_tax_excluded(excluded)
            included, excluded = line._get_display_values_from_price_unit(line_vals['price_unit'])
            line_vals.update(
                price_unit_tax_included=included,
                price_unit_tax_excluded=excluded,
            )
            super(PurchaseOrderLine, line.with_context(skip_wsd_price_sync=True)).write(line_vals)
        return True

    def _sync_display_price_values(self):
        for line in self:
            included, excluded = line._get_display_values_from_price_unit(line.price_unit)
            super(PurchaseOrderLine, line.with_context(skip_wsd_price_sync=True)).write({
                'price_unit_tax_included': included,
                'price_unit_tax_excluded': excluded,
            })
