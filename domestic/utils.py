"""Indian-format number to words for Tax Invoices (Lacs / Crores)."""

from decimal import Decimal

_ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight',
         'Nine', 'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen',
         'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen']
_TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy',
         'Eighty', 'Ninety']


def _below_hundred(n):
    if n < 20:
        return _ONES[n]
    return (_TENS[n // 10] + (' ' + _ONES[n % 10] if n % 10 else '')).strip()


def _below_thousand(n):
    if n < 100:
        return _below_hundred(n)
    rem = n % 100
    return (_ONES[n // 100] + ' Hundred' + (' ' + _below_hundred(rem) if rem else '')).strip()


def indian_number_to_words(n):
    """1970600 -> 'Nineteen Lacs Seventy Thousand & Six Hundred'."""
    n = int(n)
    if n == 0:
        return 'Zero'

    crore = n // 10000000; n %= 10000000
    lac = n // 100000;     n %= 100000
    thousand = n // 1000;  n %= 1000
    hundred = n // 100;    n %= 100
    rem = n

    segments = []
    if crore:
        segments.append(f"{_below_thousand(crore)} Crore" + ('s' if crore > 1 else ''))
    if lac:
        segments.append(f"{_below_hundred(lac)} Lac" + ('s' if lac > 1 else ''))
    if thousand:
        segments.append(f"{_below_hundred(thousand)} Thousand")
    if hundred:
        segments.append(f"{_ONES[hundred]} Hundred")
    if rem:
        segments.append(_below_hundred(rem))

    if len(segments) > 1:
        return ' '.join(segments[:-1]) + ' & ' + segments[-1]
    return segments[0]


def amount_in_words_inr(amount):
    """1970600 -> 'Nineteen Lacs Seventy Thousand & Six Hundred Only'."""
    amount = Decimal(str(amount or 0))
    whole = int(amount)
    paise = int((amount - whole) * 100)
    words = indian_number_to_words(whole)
    if paise:
        return f"{words} & {indian_number_to_words(paise)} Paise Only"
    return f"{words} Only"
