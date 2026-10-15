from decimal import Decimal
from datetime import datetime

from odoo import _, api, fields, models
from odoo.tools import formatLang
from odoo.tools.float_utils import float_compare, float_round
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

    def _format_contract_yuan(self, value):
        """Format an amount with a forced CNY symbol prefix and two decimals.

        Used by the contract footer (untaxed amount and VAT amount) to keep
        the printed output aligned with the Chinese purchase contract layout
        regardless of the configured currency symbol position.
        """
        formatted = formatLang(self.env, value, digits=2)
        return f'\u00a5{NON_BREAKING_SPACE}{formatted}'

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
    amount_tax_chinese = fields.Char(
        string='Tax Amount in Chinese',
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
        default='浙江省温州乐清市',
    )
    contract_attachment_ids = fields.Many2many(
        comodel_name='ir.attachment',
        relation='purchase_order_contract_attachment_rel',
        column1='purchase_order_id',
        column2='attachment_id',
        string='Contract Attachments',
        copy=True,
    )
    has_contract_attachment = fields.Boolean(
        string='Contract Attached',
        compute='_compute_has_contract_attachment',
        store=True,
    )
    sync_price_to_vendor_pricelist = fields.Boolean(
        string='Update Vendor Pricelist',
        default=True,
        copy=True,
        help="Write the unit prices and discounts changed on the order lines back "
             "to the vendor pricelist of the order vendor when the order is "
             "confirmed, so that the next purchase order defaults to them.",
    )

    @api.depends('contract_attachment_ids')
    def _compute_has_contract_attachment(self):
        for order in self:
            order.has_contract_attachment = bool(order.contract_attachment_ids)

    @api.depends('amount_total', 'amount_untaxed', 'amount_tax')
    def _compute_amount_total_chinese(self):
        for order in self:
            order.amount_total_chinese = cncurrency(order.amount_total, prefix=True)
            order.amount_untaxed_chinese = cncurrency(order.amount_untaxed, prefix=True)
            order.amount_tax_chinese = cncurrency(order.amount_tax, prefix=True)

    def _add_supplier_to_product(self):
        res = super()._add_supplier_to_product()
        self._sync_vendor_pricelist_prices()
        return res

    def _sync_vendor_pricelist_prices(self):
        """Remember the prices changed on the order as the default vendor prices."""
        for order in self:
            if not order.sync_price_to_vendor_pricelist:
                continue
            order.order_line._sync_price_to_vendor_pricelist()


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    brand_id = fields.Many2one(
        comodel_name='sn.wsd.brand',
        related='product_id.brand_id',
        string='Brand',
        readonly=True,
        help='Brand of the ordered product, printed on the purchase contract.',
    )
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

    def _get_price_precision(self):
        """Return the precision used by the standard flow to compare unit prices."""
        self.ensure_one()
        return max(
            self.currency_id.decimal_places,
            self.env['decimal.precision'].precision_get('Product Price'),
        )

    def _is_price_manually_changed(self):
        """Return whether the unit price of the line was changed by hand.

        The standard computation stores the price it derived from the vendor
        pricelist in ``technical_price_unit`` and stops refreshing
        ``price_unit`` as soon as both differ, which makes that difference the
        reliable flag of a manual price change.
        """
        self.ensure_one()
        return float_compare(
            self.price_unit,
            self.technical_price_unit,
            precision_digits=self._get_price_precision(),
        ) != 0

    def _get_quantity_in_seller_uom(self, seller):
        """Return the ordered quantity expressed in the unit of the vendor pricelist."""
        self.ensure_one()
        quantity = abs(self.product_qty)
        if self.product_uom_id and seller.product_uom_id != self.product_uom_id:
            quantity = self.product_uom_id._compute_quantity(quantity, seller.product_uom_id)
        return quantity

    def _find_vendor_pricelist_entry(self):
        """Return the vendor pricelist entry holding the default price of the line.

        The entry already selected by the standard flow is used when available.
        Otherwise the most specific entry (the one with the highest reached
        minimum quantity) of the order vendor for that product is returned, and
        failing that the entry with the lowest minimum quantity.
        """
        self.ensure_one()
        if self.selected_seller_id:
            return self.selected_seller_id
        partner = self.order_id.partner_id
        entries = self.product_id.seller_ids.filtered(
            lambda seller: seller.partner_id in (partner | partner.parent_id)
            and (not seller.company_id or seller.company_id == self.company_id)
            and (not seller.product_id or seller.product_id == self.product_id)
        )
        if not entries:
            return self.env['product.supplierinfo']
        precision = self.env['decimal.precision'].precision_get('Product Unit')
        reached = entries.filtered(
            lambda seller: float_compare(
                self._get_quantity_in_seller_uom(seller),
                seller.min_qty,
                precision_digits=precision,
            ) >= 0
        )
        if reached:
            return reached.sorted(key=lambda seller: (seller.min_qty, -seller.sequence, -seller.id))[-1]
        return entries.sorted(key=lambda seller: (seller.min_qty, seller.sequence, seller.id))[0]

    def _is_price_writable_to_vendor_pricelist(self):
        """Return whether the line price can be stored as the vendor price.

        A vendor price is expressed with the vendor taxes of the product. A line
        taxed differently on a price-included tax cannot be written back without
        shifting the default price of the next order.
        """
        self.ensure_one()
        line_taxes = self.tax_ids
        seller_taxes = self.product_id.supplier_taxes_id.filtered(
            lambda tax: tax.company_id == self.company_id
        )
        differing_taxes = (seller_taxes - line_taxes) | (line_taxes - seller_taxes)
        return not differing_taxes.filtered('price_include')

    def _write_price_to_vendor_pricelist(self, seller):
        """Store the line price and discount on the given vendor pricelist entry."""
        self.ensure_one()
        if not self._is_price_writable_to_vendor_pricelist():
            self.product_id.product_tmpl_id.sudo().message_post(body=_(
                "%(order)s: the vendor pricelist was not updated for %(product)s, the "
                "taxes of the order line differ from the vendor taxes of the product.",
                order=self.order_id.display_name,
                product=self.product_id.display_name,
            ))
            return
        price = self.price_unit
        if seller.product_uom_id != self.product_uom_id:
            price = self.product_uom_id._compute_price(price, seller.product_uom_id)
        if seller.currency_id != self.currency_id:
            price = self.currency_id._convert(
                price,
                seller.currency_id,
                self.company_id,
                self.order_id.date_order or fields.Date.context_today(self),
            )
        price = float_round(price, precision_digits=max(
            seller.currency_id.decimal_places,
            self.env['decimal.precision'].precision_get('Product Price'),
        ))
        discount = self.discount
        if (
            seller.currency_id.compare_amounts(price, seller.price) == 0
            and float_compare(
                discount,
                seller.discount,
                precision_digits=self.env['decimal.precision'].precision_get('Discount'),
            ) == 0
        ):
            return
        old_price = seller.price
        old_discount = seller.discount
        seller.sudo().write({
            'price': price,
            'discount': discount,
        })
        seller.product_tmpl_id.sudo().message_post(body=_(
            "%(order)s updated the vendor price of %(vendor)s from %(old_price)s to "
            "%(new_price)s %(currency)s (discount %(old_discount)s%% -> %(new_discount)s%%).",
            order=self.order_id.display_name,
            vendor=seller.partner_id.display_name,
            old_price=old_price,
            new_price=price,
            currency=seller.currency_id.name,
            old_discount=old_discount,
            new_discount=discount,
        ))

    def _sync_price_to_vendor_pricelist(self):
        """Remember the prices changed on the lines as the default vendor prices."""
        for line in self:
            if line.display_type or line.is_downpayment or not line.product_id:
                continue
            if not line._is_price_manually_changed():
                continue
            seller = line._find_vendor_pricelist_entry()
            if not seller:
                # The standard flow already created the entry of an unknown
                # vendor with the price of this line.
                continue
            line._write_price_to_vendor_pricelist(seller)
