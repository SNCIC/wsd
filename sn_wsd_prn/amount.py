"""Amounts as the paper documents print them.

The finance forms show the total of the sheet twice: in figures, in the amount
column, and in Chinese capitals, on the total row. The capitals are what the
signature is checked against, so the reading follows the accounting usage of
the forms: 170.50 is 壹佰柒拾元伍角整, 1001.05 is 壹仟零壹元零伍分.
"""

DIGITS = '零壹贰叁肆伍陆柒捌玖'
SECTION_UNITS = ('仟', '佰', '拾', '')
GROUP_UNITS = ('', '万', '亿', '万亿')

ZERO = '零'
TEN_THOUSAND = '万'
HUNDRED_MILLION = '亿'
YUAN = '元'
JIAO = '角'
FEN = '分'
WHOLE = '整'
NEGATIVE = '负'


def format_money(value, decimals=2):
    """Amount in figures, as the money columns of the forms show it."""
    return '%.*f' % (decimals, value or 0.0)


def amount_to_chinese(value):
    """Chinese capitals of an amount, in yuan, jiao and fen."""
    amount = round(float(value or 0.0), 2)
    negative = amount < 0
    amount = abs(amount)
    # The cents are read on their own: a float in yuan loses them on the way
    # through the integer part.
    cents = int(round(amount * 100))
    integer, cents = divmod(cents, 100)
    text = '%s%s' % (_read_integer(integer), YUAN)
    jiao, fen = divmod(cents, 10)
    if not jiao and not fen:
        text += WHOLE
    elif not jiao:
        text += ZERO + DIGITS[fen] + FEN
    elif not fen:
        text += DIGITS[jiao] + JIAO + WHOLE
    else:
        text += DIGITS[jiao] + JIAO + DIGITS[fen] + FEN
    return NEGATIVE + text if negative else text


def _read_integer(value):
    """Chinese reading of a whole amount, without the yuan unit."""
    if not value:
        return ZERO
    groups = []
    remaining = value
    while remaining:
        groups.append(remaining % 10000)
        remaining //= 10000
    text = ''
    for index in range(len(groups) - 1, -1, -1):
        section = groups[index]
        if not section:
            # A whole empty group is one zero, unless the reading already
            # ends on one: 10 0005 is 壹拾万零伍, not 壹拾万零零伍.
            if text and not text.endswith(ZERO):
                text += ZERO
            continue
        # A section under one thousand follows another one with its leading
        # zero: 1 0001 is 壹万零壹.
        if text and section < 1000 and not text.endswith(ZERO):
            text += ZERO
        text += _read_section(section) + GROUP_UNITS[index]
    return text.rstrip(ZERO) or ZERO


def _read_section(value):
    """Chinese reading of a four-digit section, without its group unit."""
    text = ''
    zero = False
    for index, unit in enumerate(SECTION_UNITS):
        digit = value // 10 ** (3 - index) % 10
        if digit:
            if zero and text:
                text += ZERO
            text += DIGITS[digit] + unit
            zero = False
        elif text:
            zero = True
    return text
