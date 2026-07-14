"""
Stock service — the single source of truth for "what do we actually have,
what did we pay for it, and how much of it is still free to sell".

Used by:
  • inventory.stock_views  → the dedicated Stock page (list / detail / summary)
  • sales.views.stock_items → the Stock-Sale item picker on the PI form
  • sales.serializers       → over-sell guards when a Stock-Sale PI is created/edited

Ledger rules (must match the rest of the app):
  • Stock goes UP   when a PO item is received  (PurchaseOrderItem.mark_as_purchased)
  • Stock goes DOWN when a PI is ACCEPTED       (ProformaInvoiceViewSet.accept)
  • Returns adjust Product.current_stock directly

  ⇒ Product.current_stock is the ledger truth (on-hand).
  ⇒ A DRAFT/SENT PI has NOT deducted stock yet, but those units are promised to a
    customer, so they are RESERVED. Anything sellable today is therefore:

        available_qty = current_stock - reserved_qty

    Without this, the same unit could be put on two different draft PIs.
"""

from decimal import Decimal

# PI statuses that hold stock without having deducted it yet.
RESERVING_PI_STATUSES = ('DRAFT', 'SENT')
# PI status that has already deducted stock (= genuinely sold).
SOLD_PI_STATUS = 'ACCEPTED'

ZERO = Decimal('0')


def _d(value):
    """Anything → Decimal (None/'' safe)."""
    if value is None or value == '':
        return ZERO
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _rate_effective_on(on_date):
    """
    USD→INR rate that was in force on `on_date`, read from the admin-managed
    ExchangeRate history (core.models.ExchangeRate → table `exchange_rates`,
    the same table the Currency page writes to: "1 USD = ? INR" + effective_date).

    Picks the newest row whose effective_date <= on_date. If the document predates
    every recorded rate, falls back to the OLDEST rate on record — the closest thing
    to the truth we have. Returns None when no rate is configured at all.

    Only used when a document did not store its own conversion rate.
    """
    from core.models import ExchangeRate

    if on_date:
        row = ExchangeRate.objects.filter(
            effective_date__lte=on_date
        ).order_by('-effective_date', '-created_at').first()
        if row:
            return _d(row.rate)

    # Nothing on/before that date → use the earliest rate ever recorded.
    row = ExchangeRate.objects.order_by('effective_date', 'created_at').first()
    return _d(row.rate) if row else None


def _conversion(currency, stored_rate, doc_date):
    """
    → (rate, is_estimated)

    A document (PO/PI) is supposed to freeze its own conversion rate at creation.
    Older rows left it NULL on non-INR documents; treating those as 1 would silently
    value a $8,000 purchase at ₹8,000. So we fall back to the exchange rate that was
    in force on the document's date and mark the number ESTIMATED, instead of quietly
    reporting a wrong cost.

    The ExchangeRate table only holds USD→INR, so the fallback is applied to USD
    only. Any other currency without a stored rate stays at 1 and is flagged — that
    figure is not trustworthy and the UI says so.
    """
    if currency == 'INR':
        return Decimal('1'), False

    stored = _d(stored_rate)
    if stored > ZERO:
        return stored, False

    if currency == 'USD':
        fallback = _rate_effective_on(doc_date)
        if fallback and fallback > ZERO:
            return fallback, True

    return Decimal('1'), True


def _po_conversion(po):
    return _conversion(po.currency, po.conversion_rate, po.po_date)


def _pi_conversion(pi):
    return _conversion(pi.currency, pi.conversion_rate, pi.pi_date)


# ─────────────────────────────────────────────────────────────────────────────
# Reservations
# ─────────────────────────────────────────────────────────────────────────────

def reserved_qty_map(product_ids=None, exclude_pi_id=None):
    """
    {product_id: Decimal} — quantity locked inside open (DRAFT/SENT) PIs.

    exclude_pi_id: ignore this PI's own lines (used while editing that PI, so its
                   existing quantities don't count against itself).
    """
    from django.db.models import Sum
    from sales.models import ProformaInvoiceItem

    qs = ProformaInvoiceItem.objects.filter(
        proforma_invoice__status__in=RESERVING_PI_STATUSES
    )
    if product_ids is not None:
        qs = qs.filter(product_id__in=list(product_ids))
    if exclude_pi_id:
        qs = qs.exclude(proforma_invoice_id=exclude_pi_id)

    rows = qs.values('product_id').annotate(qty=Sum('quantity'))
    return {r['product_id']: _d(r['qty']) for r in rows}


def available_qty(product, exclude_pi_id=None):
    """How much of `product` can still be put on a new Stock-Sale PI today."""
    reserved = reserved_qty_map([product.id], exclude_pi_id=exclude_pi_id).get(product.id, ZERO)
    return _d(product.current_stock) - reserved


# ─────────────────────────────────────────────────────────────────────────────
# Purchase / sale aggregates
# ─────────────────────────────────────────────────────────────────────────────

def _purchase_lines(product_ids):
    """Received, non-cancelled PO lines for the given products, oldest first."""
    from purchase_orders.models import PurchaseOrderItem

    return list(
        PurchaseOrderItem.objects.filter(
            product_id__in=list(product_ids), is_received=True
        ).exclude(
            po__status='CANCELLED'
        ).select_related('po', 'po__vendor', 'po__requisition').order_by('po__po_date', 'po__created_at')
    )


def _open_purchase_lines(product_ids):
    """PO lines raised but NOT yet received (on order / in transit)."""
    from purchase_orders.models import PurchaseOrderItem

    return list(
        PurchaseOrderItem.objects.filter(
            product_id__in=list(product_ids), is_received=False
        ).exclude(
            po__status='CANCELLED'
        ).select_related('po', 'po__vendor', 'po__requisition').order_by('-po__po_date')
    )


def _sale_lines(product_ids):
    """Non-cancelled PI lines for the given products, oldest first."""
    from sales.models import ProformaInvoiceItem

    return list(
        ProformaInvoiceItem.objects.filter(
            product_id__in=list(product_ids)
        ).exclude(
            proforma_invoice__status='CANCELLED'
        ).select_related('proforma_invoice').order_by('proforma_invoice__pi_date', 'proforma_invoice__created_at')
    )


def purchase_stats(product_ids):
    """
    {product_id: {...}} — everything about "kitni baar, kis price me kharida".
    All money values normalised to INR using the PO's own conversion rate.
    """
    stats = {}
    for poi in _purchase_lines(product_ids):
        po = poi.po
        conv, estimated = _po_conversion(po)
        qty = _d(poi.quantity)
        rate_inr = _d(poi.rate) * conv
        amount_inr = _d(poi.amount) * conv

        s = stats.setdefault(poi.product_id, {
            'purchase_count': 0,
            'total_purchased_qty': ZERO,
            'total_purchase_value': ZERO,   # INR
            'min_purchase_rate': None,      # INR
            'max_purchase_rate': None,      # INR
            'first_purchase_date': None,
            'last_purchase_date': None,
            'last_purchase_rate': ZERO,          # INR
            'last_purchase_rate_original': ZERO,  # PO currency
            'last_purchase_currency': 'INR',
            'last_purchase_conversion_rate': Decimal('1'),
            'last_purchase_rate_estimated': False,
            'has_foreign_currency': False,
            'has_estimated_rate': False,
            'last_purchase_qty': ZERO,
            'last_vendor_name': '',
            'last_po_number': '',
            'last_requisition_number': '',
            'prev_purchase_rate': None,     # INR — the one before the latest
            'vendors': [],
        })

        s['purchase_count'] += 1
        s['total_purchased_qty'] += qty
        s['total_purchase_value'] += amount_inr
        s['min_purchase_rate'] = rate_inr if s['min_purchase_rate'] is None else min(s['min_purchase_rate'], rate_inr)
        s['max_purchase_rate'] = rate_inr if s['max_purchase_rate'] is None else max(s['max_purchase_rate'], rate_inr)
        if s['first_purchase_date'] is None:
            s['first_purchase_date'] = po.po_date

        # Lines arrive oldest-first, so the last one seen is the latest purchase.
        s['prev_purchase_rate'] = s['last_purchase_rate'] if s['purchase_count'] > 1 else None
        s['last_purchase_date'] = po.po_date
        s['last_purchase_rate'] = rate_inr
        s['last_purchase_rate_original'] = _d(poi.rate)
        s['last_purchase_currency'] = po.currency
        s['last_purchase_conversion_rate'] = conv
        s['last_purchase_rate_estimated'] = estimated
        s['last_purchase_qty'] = qty
        if po.currency != 'INR':
            s['has_foreign_currency'] = True
        if estimated:
            s['has_estimated_rate'] = True
        s['last_vendor_name'] = po.vendor.vendor_name if po.vendor else ''
        s['last_po_number'] = po.po_number
        s['last_requisition_number'] = po.requisition.requisition_number if po.requisition else ''

        vname = po.vendor.vendor_name if po.vendor else ''
        if vname and vname not in s['vendors']:
            s['vendors'].append(vname)

    for s in stats.values():
        qty = s['total_purchased_qty']
        s['avg_purchase_rate'] = (s['total_purchase_value'] / qty) if qty else ZERO
        prev = s['prev_purchase_rate']
        if prev is None or prev == ZERO:
            s['price_trend'] = 'FLAT'
            s['price_change_pct'] = ZERO
        else:
            diff = s['last_purchase_rate'] - prev
            s['price_change_pct'] = (diff / prev) * Decimal('100')
            s['price_trend'] = 'UP' if diff > 0 else ('DOWN' if diff < 0 else 'FLAT')

    return stats


def sale_stats(product_ids):
    """{product_id: {...}} — sold (ACCEPTED) vs reserved (DRAFT/SENT)."""
    stats = {}
    for pii in _sale_lines(product_ids):
        pi = pii.proforma_invoice
        conv, _estimated = _pi_conversion(pi)
        qty = _d(pii.quantity)
        price_inr = _d(pii.unit_price) * conv

        s = stats.setdefault(pii.product_id, {
            'sale_count': 0,
            'total_sold_qty': ZERO,
            'total_sale_value': ZERO,      # INR, ACCEPTED only
            'reserved_qty': ZERO,
            'open_pi_count': 0,
            'last_sale_date': None,
            'last_sale_price': ZERO,       # INR
            'last_pi_number': '',
        })

        if pi.status == SOLD_PI_STATUS:
            s['sale_count'] += 1
            s['total_sold_qty'] += qty
            s['total_sale_value'] += _d(pii.amount) * conv
            s['last_sale_date'] = pi.pi_date
            s['last_sale_price'] = price_inr
            s['last_pi_number'] = pi.pi_number
        elif pi.status in RESERVING_PI_STATUSES:
            s['reserved_qty'] += qty
            s['open_pi_count'] += 1

    return stats


# ─────────────────────────────────────────────────────────────────────────────
# Row builder (list view + PI stock picker share this)
# ─────────────────────────────────────────────────────────────────────────────

def _empty_purchase():
    return {
        'purchase_count': 0, 'total_purchased_qty': ZERO, 'total_purchase_value': ZERO,
        'min_purchase_rate': None, 'max_purchase_rate': None, 'avg_purchase_rate': ZERO,
        'first_purchase_date': None, 'last_purchase_date': None,
        'last_purchase_rate': ZERO, 'last_purchase_rate_original': ZERO,
        'last_purchase_currency': 'INR', 'last_purchase_conversion_rate': Decimal('1'),
        'last_purchase_rate_estimated': False,
        'has_foreign_currency': False, 'has_estimated_rate': False,
        'last_purchase_qty': ZERO,
        'last_vendor_name': '', 'last_po_number': '', 'last_requisition_number': '',
        'prev_purchase_rate': None, 'price_trend': 'FLAT', 'price_change_pct': ZERO,
        'vendors': [],
    }


def _empty_sale():
    return {
        'sale_count': 0, 'total_sold_qty': ZERO, 'total_sale_value': ZERO,
        'reserved_qty': ZERO, 'open_pi_count': 0,
        'last_sale_date': None, 'last_sale_price': ZERO, 'last_pi_number': '',
    }


def build_stock_rows(products, exclude_pi_id=None):
    """
    products: iterable of Product
    → list of plain dicts (JSON-ready) with purchase / sale / availability facts.
    Runs a fixed number of queries regardless of how many products are passed.
    """
    products = list(products)
    ids = [p.id for p in products]
    if not ids:
        return []

    pstats = purchase_stats(ids)
    sstats = sale_stats(ids)
    reserved = reserved_qty_map(ids, exclude_pi_id=exclude_pi_id)

    rows = []
    for p in products:
        ps = pstats.get(p.id) or _empty_purchase()
        ss = sstats.get(p.id) or _empty_sale()

        on_hand = _d(p.current_stock)
        res = reserved.get(p.id, ZERO)
        avail = on_hand - res

        # Valuation at weighted-average purchase cost, falling back to the last
        # known buying price and finally the item-master rate.
        unit_cost = ps['avg_purchase_rate'] or ps['last_purchase_rate'] or _d(p.rate)

        rows.append({
            'product_id': str(p.id),
            'item_code': p.item_code,
            'item_name': p.item_name,
            'hsn_code': p.hsn_code,
            'unit': p.unit,
            'is_active': p.is_active,
            'reorder_level': float(_d(p.reorder_level)),

            # ── availability ────────────────────────────────────────────────
            'current_stock': float(on_hand),
            'reserved_qty': float(res),
            'available_qty': float(avail),
            'open_pi_count': ss['open_pi_count'],
            'is_low_stock': bool(on_hand > 0 and on_hand <= _d(p.reorder_level)),
            'is_out_of_stock': bool(on_hand <= 0),

            # ── purchases: kitni baar, kis price me ─────────────────────────
            'purchase_count': ps['purchase_count'],
            'total_purchased_qty': float(ps['total_purchased_qty']),
            'total_purchase_value': float(round(ps['total_purchase_value'], 2)),
            'avg_purchase_rate': float(round(ps['avg_purchase_rate'], 2)),
            'min_purchase_rate': float(round(ps['min_purchase_rate'], 2)) if ps['min_purchase_rate'] is not None else 0.0,
            'max_purchase_rate': float(round(ps['max_purchase_rate'], 2)) if ps['max_purchase_rate'] is not None else 0.0,
            'last_purchase_rate': float(round(ps['last_purchase_rate'], 2)),
            'last_purchase_rate_original': float(round(ps['last_purchase_rate_original'], 2)),
            'last_purchase_currency': ps['last_purchase_currency'],
            'last_purchase_conversion_rate': float(ps['last_purchase_conversion_rate']),
            'last_purchase_rate_estimated': ps['last_purchase_rate_estimated'],
            'has_foreign_currency': ps['has_foreign_currency'],
            'has_estimated_rate': ps['has_estimated_rate'],
            'last_purchase_qty': float(ps['last_purchase_qty']),
            'last_purchase_date': ps['last_purchase_date'],
            'first_purchase_date': ps['first_purchase_date'],
            'last_vendor_name': ps['last_vendor_name'],
            'last_po_number': ps['last_po_number'],
            'last_requisition_number': ps['last_requisition_number'],
            'vendors': ps['vendors'],
            'price_trend': ps['price_trend'],
            'price_change_pct': float(round(ps['price_change_pct'], 2)),

            # ── sales ───────────────────────────────────────────────────────
            'sale_count': ss['sale_count'],
            'total_sold_qty': float(ss['total_sold_qty']),
            'total_sale_value': float(round(ss['total_sale_value'], 2)),
            'last_sale_price': float(round(ss['last_sale_price'], 2)),
            'last_sale_date': ss['last_sale_date'],
            'last_pi_number': ss['last_pi_number'],

            # ── valuation ───────────────────────────────────────────────────
            'unit_cost': float(round(unit_cost, 2)),
            'stock_value': float(round(on_hand * unit_cost, 2)),
            'available_value': float(round(max(avail, ZERO) * unit_cost, 2)),
        })

    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Detail ledger (one product)
# ─────────────────────────────────────────────────────────────────────────────

def product_ledger(product):
    """Full purchase + sale history of one product, newest first."""
    ids = [product.id]

    purchases = []
    for poi in reversed(_purchase_lines(ids)):
        po = poi.po
        conv, estimated = _po_conversion(po)
        purchases.append({
            'conversion_rate_estimated': estimated,
            'po_id': str(po.id),
            'po_number': po.po_number,
            'po_date': po.po_date,
            'vendor_name': po.vendor.vendor_name if po.vendor else '',
            'requisition_number': po.requisition.requisition_number if po.requisition else '',
            'quantity': float(_d(poi.quantity)),
            'rate': float(_d(poi.rate)),
            'amount': float(_d(poi.amount)),
            'currency': po.currency,
            'conversion_rate': float(conv),
            'rate_inr': float(round(_d(poi.rate) * conv, 2)),
            'amount_inr': float(round(_d(poi.amount) * conv, 2)),
            'po_status': po.status,
            'received': True,
        })

    on_order = []
    for poi in _open_purchase_lines(ids):
        po = poi.po
        conv, estimated = _po_conversion(po)
        on_order.append({
            'conversion_rate_estimated': estimated,
            'po_id': str(po.id),
            'po_number': po.po_number,
            'po_date': po.po_date,
            'vendor_name': po.vendor.vendor_name if po.vendor else '',
            'requisition_number': po.requisition.requisition_number if po.requisition else '',
            'quantity': float(_d(poi.quantity)),
            'rate': float(_d(poi.rate)),
            'amount': float(_d(poi.amount)),
            'currency': po.currency,
            'conversion_rate': float(conv),
            'rate_inr': float(round(_d(poi.rate) * conv, 2)),
            'amount_inr': float(round(_d(poi.amount) * conv, 2)),
            'po_status': po.status,
            'received': False,
        })

    sales = []
    for pii in reversed(_sale_lines(ids)):
        pi = pii.proforma_invoice
        conv, estimated = _pi_conversion(pi)
        buyer = (pi.consignee or pi.applicant_importer or '').strip().splitlines()
        sales.append({
            'conversion_rate_estimated': estimated,
            'pi_id': str(pi.id),
            'pi_number': pi.pi_number,
            'pi_date': pi.pi_date,
            'status': pi.status,
            'source': pi.source,
            'trade_type': pi.trade_type,
            'buyer': buyer[0] if buyer else '',
            'quantity': float(_d(pii.quantity)),
            'unit_price': float(_d(pii.unit_price)),
            'amount': float(_d(pii.amount)),
            'currency': pi.currency,
            'conversion_rate': float(conv),
            'unit_price_inr': float(round(_d(pii.unit_price) * conv, 2)),
            'amount_inr': float(round(_d(pii.amount) * conv, 2)),
            'is_sold': pi.status == SOLD_PI_STATUS,
            'is_reserved': pi.status in RESERVING_PI_STATUSES,
        })

    row = build_stock_rows([product])[0]
    row['purchases'] = purchases
    row['on_order'] = on_order
    row['sales'] = sales
    row['on_order_qty'] = float(sum(_d(o['quantity']) for o in on_order))
    return row
