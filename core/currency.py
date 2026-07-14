"""
Currency conversion — one rule for the whole system.

Every module used to do its own thing, and all of them shared the same flaw:

    if currency == 'INR' or not conversion_rate:
        return amount            # ← a $185,000 PO silently became ₹185,000

…while reports/ and dashboard/ did not convert at all — they added USD straight
onto INR with a plain Sum('total_amount').

The rule here:

  • INR                      → the amount, as-is.
  • Non-INR WITH a rate      → amount × rate.
  • Non-INR WITHOUT a rate   → NOT convertible. It is never fabricated. Callers
                               exclude it from totals and surface it, so somebody
                               fixes the document instead of trusting a wrong number.

A document is supposed to freeze its own rate when it is created (PO and PI now
require one for non-INR). This path only exists for rows created before that.
"""

from decimal import Decimal

ZERO = Decimal('0')


def _d(value):
    if value is None or value == '':
        return ZERO
    return value if isinstance(value, Decimal) else Decimal(str(value))


def to_inr(amount, currency, conversion_rate):
    """→ (value_in_inr, is_convertible)"""
    if not currency or currency == 'INR':
        return _d(amount), True
    rate = _d(conversion_rate)
    if rate <= ZERO:
        return ZERO, False
    return _d(amount) * rate, True


def inr(amount, currency, conversion_rate):
    """
    → Decimal, or 0 when the document has no rate.

    Use where a caller just needs a number. Excluding an unvalued document
    understates a total; PRETENDING a $185,000 PO is ₹185,000 corrupts it. Pair
    this with unconvertible_docs() so the excluded rows are visible.
    """
    value, ok = to_inr(amount, currency, conversion_rate)
    return value if ok else ZERO


def sum_inr(rows, amount_attr, currency_attr='currency', rate_attr='conversion_rate'):
    """
    → (total_inr, skipped_rows)

    Sums an iterable of model instances in INR, returning the rows it could not
    value so the caller can report them.
    """
    total = ZERO
    skipped = []
    for row in rows:
        value, ok = to_inr(
            getattr(row, amount_attr, None),
            getattr(row, currency_attr, 'INR'),
            getattr(row, rate_attr, None),
        )
        if ok:
            total += value
        else:
            skipped.append(row)
    return total, skipped


def unconvertible_docs():
    """
    Every live document in a foreign currency with no conversion rate stored.
    Drives the "fix these" warnings on the finance pages.
    """
    from purchase_orders.models import PurchaseOrder
    from sales.models import ProformaInvoice

    out = []
    for po in PurchaseOrder.objects.exclude(status='CANCELLED').exclude(currency='INR'):
        if _d(po.conversion_rate) <= ZERO:
            out.append({
                'doc_type': 'PURCHASE_ORDER', 'number': po.po_number,
                'currency': po.currency, 'amount': float(po.total_amount or 0),
                'message': 'Conversion rate not set — excluded from all INR totals.',
            })
    for pi in ProformaInvoice.objects.exclude(status='CANCELLED').exclude(currency='INR'):
        if _d(pi.conversion_rate) <= ZERO:
            out.append({
                'doc_type': 'PROFORMA_INVOICE', 'number': pi.pi_number,
                'currency': pi.currency, 'amount': float(pi.grand_total or 0),
                'message': 'Conversion rate not set — excluded from all INR totals.',
            })
    return out


def validate_rate(currency, conversion_rate, doc_label='document', date_label='its date'):
    """
    Serializer guard: a non-INR document must carry the rate it was booked at.

    Call this from every serializer that lets a user pick a currency. Without it
    the row lands in the database unvaluable, and every INR report either drops it
    or (worse, as it used to) counts $185,000 as ₹185,000.
    """
    from rest_framework import serializers

    if not currency or currency == 'INR':
        return
    if _d(conversion_rate) > ZERO:
        return
    raise serializers.ValidationError({
        'conversion_rate': (
            f'Required for a non-INR {doc_label} ({currency}). '
            f'Enter the INR conversion rate applicable on {date_label}.'
        )
    })
