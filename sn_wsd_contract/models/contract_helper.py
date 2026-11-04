"""Chinese currency wording printed on the contracts.

The purchase contract of the purchase module carries the same wording helper;
it is repeated here rather than imported, so that a contract report does not
depend on the purchase module.
"""
from decimal import Decimal


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
