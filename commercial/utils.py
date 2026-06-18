"""Helpers for Commercial Invoice / Packing List."""

from decimal import Decimal

_ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight',
         'Nine', 'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen',
         'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen']
_TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy',
         'Eighty', 'Ninety']
# International grouping (export documents use Thousand / Million / Billion)
_SCALES = [(10 ** 9, 'Billion'), (10 ** 6, 'Million'), (10 ** 3, 'Thousand')]


def _three_digit_words(n):
    """Words for 0..999."""
    words = []
    if n >= 100:
        words.append(_ONES[n // 100])
        words.append('Hundred')
        n %= 100
        if n:
            words.append('and')
    if n >= 20:
        words.append(_TENS[n // 10])
        if n % 10:
            words.append(_ONES[n % 10])
    elif n > 0:
        words.append(_ONES[n])
    return words


def number_to_words(n):
    """Integer -> English words (international system). 0 -> 'Zero'."""
    n = int(n)
    if n == 0:
        return 'Zero'
    parts = []
    for value, name in _SCALES:
        if n >= value:
            parts.extend(_three_digit_words(n // value))
            parts.append(name)
            n %= value
    if n:
        parts.extend(_three_digit_words(n))
    return ' '.join(parts)


def amount_in_words(amount, currency='USD'):
    """
    Money -> words, e.g. 18130.00 -> 'Eighteen Thousand One Hundred and Thirty Only.'
    Includes a cents/fraction clause only when there is a fractional part.
    """
    amount = Decimal(str(amount or 0))
    whole = int(amount)
    fraction = int((amount - whole) * 100)
    words = number_to_words(whole)
    if fraction:
        return f"{words} and {number_to_words(fraction)} Cents Only."
    return f"{words} Only."
