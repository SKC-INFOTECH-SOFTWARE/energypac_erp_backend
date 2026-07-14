"""
Profit & Loss — one calculation, used by every finance endpoint.

Before this module, /finance/profit-loss, /finance/revenue-analytics and
/finance/dashboard each did their own arithmetic and disagreed with one another.
They now all call compute_pnl().

The accounting model
--------------------
Money going out on purchases is NOT automatically a cost. It becomes a cost only
when the goods are sold; until then it is inventory (an asset). So:

    Revenue  = ACCEPTED Proforma Invoices only.
               A DRAFT/SENT PI is a quote, not a sale — it is reported separately
               as `pipeline`.

    COGS     = for every sold line, what that item actually cost us:
                 • requisition sale → weighted-average rate of the PO(s) raised for
                   that requisition + product
                 • stock / direct   → weighted-average rate across all POs for that
                   product
               This is why the cost of a stock sale is no longer double-counted:
               the requisition row only carries the cost of what it actually sold,
               and the rest sits in `inventory`.

    Inventory = total purchases − COGS   (goods bought but not yet sold)

    Transport = freight is paid to the transporter on BOTH legs and is pure cost:
                  • BUY  leg — bringing the goods in against a Purchase Order.
                    Charged to a deal in proportion to how much of that
                    requisition's stock it actually sold.
                  • SELL leg — shipping the goods out against a Proforma Invoice.
                    Charged to that deal in full.
                (TransportEntry.amount_paid is what WE paid the transporter — the
                old report credited it as "freight recovered from the client",
                which turned an expense into income. Freight charged to the client
                is already inside the PI's unit prices.)

    Gross profit = Revenue − COGS − transport

Foreign currency
----------------
A PO/PI in USD is worthless without the rate it was booked at. If a non-INR
document has no conversion_rate stored, it is NOT silently treated as rupees
(that used to hide a $185,000 PO as ₹185,000). It is excluded from the totals and
listed in `fx_warnings` so the rate can be filled in.
"""

from decimal import Decimal
from datetime import date as date_type

from django.db.models import Sum

ZERO = Decimal('0')


def D(value):
    if value is None or value == '':
        return ZERO
    return value if isinstance(value, Decimal) else Decimal(str(value))


def to_inr(amount, currency, conversion_rate):
    """
    → (value_in_inr, is_convertible)

    is_convertible is False for a non-INR document with no stored rate. Callers
    must exclude those from totals and surface them instead of guessing.
    """
    if currency == 'INR':
        return D(amount), True
    rate = D(conversion_rate)
    if rate <= ZERO:
        return ZERO, False
    return D(amount) * rate, True


def fy_bounds(fy):
    try:
        y = int(str(fy).split('-')[0])
        return date_type(y, 4, 1), date_type(y + 1, 3, 31)
    except (ValueError, IndexError, AttributeError, TypeError):
        return None, None


# ─────────────────────────────────────────────────────────────────────────────
# Unit costs
# ─────────────────────────────────────────────────────────────────────────────

def _po_item_cost(qs):
    """Weighted-average INR rate over a set of PO lines. → (rate, had_unconvertible)"""
    total_amount = ZERO
    total_qty = ZERO
    skipped = False
    for poi in qs.select_related('po'):
        value, ok = to_inr(poi.amount, poi.po.currency, poi.po.conversion_rate)
        if not ok:
            skipped = True
            continue
        total_amount += value
        total_qty += D(poi.quantity)
    if total_qty <= ZERO:
        return ZERO, skipped
    return total_amount / total_qty, skipped


def unit_cost_for_sold_item(pi_item):
    """
    What one unit of this sold item actually cost us.
    → (rate_inr, source) where source is 'REQUISITION' | 'STOCK' | 'UNKNOWN'
    """
    from purchase_orders.models import PurchaseOrderItem

    if pi_item.requisition_item_id:
        req_id = pi_item.requisition_item.requisition_id
        rate, _ = _po_item_cost(
            PurchaseOrderItem.objects.filter(
                po__requisition_id=req_id, product_id=pi_item.product_id
            ).exclude(po__status='CANCELLED')
        )
        if rate > ZERO:
            return rate, 'REQUISITION'

    rate, _ = _po_item_cost(
        PurchaseOrderItem.objects.filter(
            product_id=pi_item.product_id, is_received=True
        ).exclude(po__status='CANCELLED')
    )
    if rate > ZERO:
        return rate, 'STOCK'

    # Never bought through a PO — typically a Direct PI on a catalogue item.
    return ZERO, 'UNKNOWN'


# ─────────────────────────────────────────────────────────────────────────────
# The calculation
# ─────────────────────────────────────────────────────────────────────────────

def compute_pnl(fy=None, requisition_id=None):
    from purchase_orders.models import PurchaseOrder
    from sales.models import ProformaInvoice
    from transport.models import TransportEntry, TransportPayment
    from finance.models import PurchasePayment
    from billing.models import PIBillPayment

    fy_start, fy_end = fy_bounds(fy) if fy else (None, None)
    fx_warnings = []
    cost_warnings = []

    # ── 1. Purchases (money committed to vendors) ────────────────────────────
    purchases_by_req = {}
    total_purchases = ZERO
    for po in PurchaseOrder.objects.exclude(status='CANCELLED').select_related('requisition'):
        value, ok = to_inr(po.total_amount, po.currency, po.conversion_rate)
        if not ok:
            fx_warnings.append({
                'doc_type': 'PURCHASE_ORDER',
                'number': po.po_number,
                'currency': po.currency,
                'amount': float(po.total_amount or 0),
                'message': 'Conversion rate not set — excluded from all INR totals.',
            })
            continue
        total_purchases += value
        purchases_by_req[po.requisition_id] = purchases_by_req.get(po.requisition_id, ZERO) + value

    # ── 2. Transport ─────────────────────────────────────────────────────────
    buy_transport_by_req = {}
    for te in TransportEntry.objects.exclude(status='CANCELLED').filter(
        purchase_order__isnull=False
    ).select_related('purchase_order'):
        rid = te.purchase_order.requisition_id
        buy_transport_by_req[rid] = buy_transport_by_req.get(rid, ZERO) + D(te.total_cost)

    sell_transport_by_pi = {}
    for te in TransportEntry.objects.exclude(status='CANCELLED').filter(
        proforma_invoice__isnull=False
    ):
        pid = te.proforma_invoice_id
        sell_transport_by_pi[pid] = sell_transport_by_pi.get(pid, ZERO) + D(te.total_cost)

    total_transport = D(
        TransportEntry.objects.exclude(status='CANCELLED').aggregate(t=Sum('total_cost'))['t']
    )
    buy_transport_total = sum(buy_transport_by_req.values(), ZERO)
    sell_transport_total = sum(sell_transport_by_pi.values(), ZERO)

    # ── 3. Sales — ACCEPTED PIs only ─────────────────────────────────────────
    accepted = ProformaInvoice.objects.filter(status='ACCEPTED').select_related('requisition')
    if requisition_id:
        accepted = accepted.filter(requisition_id=requisition_id)
    if fy_start:
        accepted = accepted.filter(pi_date__gte=fy_start, pi_date__lte=fy_end)

    # deal = one requisition (all its accepted PIs) or one stock/direct PI
    deals_by_key = {}
    cogs_by_req = {}
    total_revenue = ZERO
    total_cogs = ZERO

    for pi in accepted:
        revenue, ok = to_inr(pi.grand_total, pi.currency, pi.conversion_rate)
        if not ok:
            fx_warnings.append({
                'doc_type': 'PROFORMA_INVOICE',
                'number': pi.pi_number,
                'currency': pi.currency,
                'amount': float(pi.grand_total or 0),
                'message': 'Conversion rate not set — excluded from all INR totals.',
            })
            continue

        pi_cogs = ZERO
        for item in pi.items.select_related('product', 'requisition_item').all():
            rate, source = unit_cost_for_sold_item(item)
            if source == 'UNKNOWN':
                cost_warnings.append({
                    'pi_number': pi.pi_number,
                    'product': item.product.item_name,
                    'message': 'Never purchased through a PO — its cost is unknown, so profit on it is overstated.',
                })
            pi_cogs += rate * D(item.quantity)

        total_revenue += revenue
        total_cogs += pi_cogs

        sell_transport = sell_transport_by_pi.get(pi.id, ZERO)

        if pi.requisition_id:
            key = ('REQ', pi.requisition_id)
            label = pi.requisition.requisition_number
            cogs_by_req[pi.requisition_id] = cogs_by_req.get(pi.requisition_id, ZERO) + pi_cogs
        else:
            key = ('PI', pi.id)
            label = pi.pi_number

        deal = deals_by_key.setdefault(key, {
            'requisition_id': str(pi.requisition_id) if pi.requisition_id else None,
            'requisition_number': label,
            'requisition_date': (pi.requisition.requisition_date.isoformat()
                                 if pi.requisition_id and pi.requisition.requisition_date
                                 else pi.pi_date.isoformat() if pi.pi_date else None),
            'pi_numbers': [],
            'purchase_cost_inr': ZERO,
            'transport_in_inr': ZERO,    # freight to bring the goods in (BUY leg)
            'transport_out_inr': ZERO,   # freight to ship them to the client (SELL leg)
            'sales_revenue_inr': ZERO,
            'is_stock_sale': not pi.requisition_id,
            'source': pi.source,
            'trade_type': pi.trade_type,
            'pi_date': pi.pi_date.isoformat() if pi.pi_date else None,
        })
        if deal['source'] != pi.source:
            deal['source'] = 'MIXED'
        if deal['trade_type'] != pi.trade_type:
            deal['trade_type'] = 'MIXED'
        deal['pi_numbers'].append(pi.pi_number)
        deal['purchase_cost_inr'] += pi_cogs
        deal['sales_revenue_inr'] += revenue
        deal['transport_out_inr'] += sell_transport

    # Inbound freight belongs to the goods, so a deal carries only the share that
    # matches the stock it actually sold (the rest stays with the unsold stock).
    for (kind, key), deal in deals_by_key.items():
        if kind != 'REQ':
            continue
        purchased = purchases_by_req.get(key, ZERO)
        buy_transport = buy_transport_by_req.get(key, ZERO)
        if purchased > ZERO and buy_transport > ZERO:
            sold_fraction = min(cogs_by_req.get(key, ZERO) / purchased, Decimal('1'))
            deal['transport_in_inr'] += buy_transport * sold_fraction

    results = []
    for deal in deals_by_key.values():
        revenue = deal['sales_revenue_inr']
        transport = deal['transport_in_inr'] + deal['transport_out_inr']
        cost = deal['purchase_cost_inr'] + transport
        profit = revenue - cost
        margin = (profit / revenue * 100) if revenue > ZERO else ZERO
        results.append({
            **deal,
            'pi_numbers': ', '.join(deal['pi_numbers']),
            'purchase_cost_inr': float(round(deal['purchase_cost_inr'], 2)),
            'transport_in_inr': float(round(deal['transport_in_inr'], 2)),
            'transport_out_inr': float(round(deal['transport_out_inr'], 2)),
            'transport_cost_inr': float(round(transport, 2)),
            'total_cost_inr': float(round(cost, 2)),
            'sales_revenue_inr': float(round(revenue, 2)),
            'profit_loss_inr': float(round(profit, 2)),
            'margin_percentage': round(float(margin), 2),
            'alert': 'LOSS' if profit < ZERO else ('LOW_MARGIN' if margin < 10 else None),
        })
    results.sort(key=lambda r: r['profit_loss_inr'])

    # ── 4. Pipeline — quoted but not sold ────────────────────────────────────
    pipeline = ZERO
    pipeline_count = 0
    for pi in ProformaInvoice.objects.filter(status__in=('DRAFT', 'SENT')):
        value, ok = to_inr(pi.grand_total, pi.currency, pi.conversion_rate)
        if ok:
            pipeline += value
            pipeline_count += 1

    # ── 5. Cash actually moved ───────────────────────────────────────────────
    cash_out = ZERO
    for po in PurchaseOrder.objects.exclude(status='CANCELLED'):
        value, ok = to_inr(po.amount_paid, po.currency, po.conversion_rate)
        if ok:
            cash_out += value
    transport_paid = D(TransportPayment.objects.aggregate(t=Sum('amount'))['t'])
    cash_out += transport_paid

    # Client money arrives on the bill, not on the PI — count both, never twice:
    # a PI's amount_received is only used when it has no bill payments behind it.
    bill_receipts = D(PIBillPayment.objects.aggregate(t=Sum('amount'))['t'])
    billed_pi_ids = set(
        PIBillPayment.objects.values_list('pi_bill__proforma_invoice_id', flat=True)
    )
    pi_receipts = ZERO
    from sales.models import ProformaInvoice as PI
    for pi in PI.objects.exclude(status='CANCELLED').exclude(id__in=billed_pi_ids):
        value, ok = to_inr(pi.amount_received, pi.currency, pi.conversion_rate)
        if ok:
            pi_receipts += value
    cash_in = bill_receipts + pi_receipts

    # ── 6. Totals ────────────────────────────────────────────────────────────
    charged_transport = sum(D(r['transport_cost_inr']) for r in results)
    total_cost = total_cogs + charged_transport
    gross_profit = total_revenue - total_cost
    inventory = total_purchases - total_cogs
    unabsorbed_transport = total_transport - charged_transport

    return {
        'currency': 'INR',
        'summary': {
            # ── Sold: revenue vs what it cost to buy and move ────────────────
            'total_revenue': float(round(total_revenue, 2)),           # ACCEPTED PIs only
            'total_purchase_cost': float(round(total_cogs, 2)),        # COGS — sold goods only
            'total_transport_cost': float(round(charged_transport, 2)),
            'total_cost': float(round(total_cost, 2)),
            'total_profit_loss': float(round(gross_profit, 2)),
            'overall_margin': round(float(gross_profit / total_revenue * 100), 2) if total_revenue > ZERO else 0.0,

            # ── Money out (whole system) ─────────────────────────────────────
            'total_purchases_inr': float(round(total_purchases, 2)),   # every non-cancelled PO
            'transport_in_inr': float(round(buy_transport_total, 2)),  # freight paid to bring goods in
            'transport_out_inr': float(round(sell_transport_total, 2)),# freight paid to ship goods out
            'total_transport_billed': float(round(total_transport, 2)),
            'total_money_out_inr': float(round(total_purchases + total_transport, 2)),

            # ── Still on the shelf ───────────────────────────────────────────
            'inventory_value_inr': float(round(inventory, 2)),         # bought, not yet sold
            'unabsorbed_transport_inr': float(round(unabsorbed_transport, 2)),

            # ── Not a sale yet ───────────────────────────────────────────────
            'pipeline_value_inr': float(round(pipeline, 2)),
            'pipeline_count': pipeline_count,

            # ── Actual cash ──────────────────────────────────────────────────
            'cash_in': float(round(cash_in, 2)),
            'cash_out': float(round(cash_out, 2)),
            'transport_cash_out': float(round(transport_paid, 2)),
            'net_cash': float(round(cash_in - cash_out, 2)),
        },
        'requisitions': results,
        'fx_warnings': fx_warnings,
        'cost_warnings': cost_warnings[:25],
    }
