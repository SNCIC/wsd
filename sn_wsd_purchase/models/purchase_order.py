from decimal import Decimal
from datetime import datetime

from odoo import api, fields, models


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
