"""
Procurement linkage for Direct PIs.

A DIRECT proforma invoice is sold ad-hoc with no requisition, so its items
have no purchase order and therefore no cost — which breaks revenue/profit
tracking. To fix that transparently we auto-create a backing Requisition that
mirrors the PI items and link it to the PI. The existing PO flow and the
per-requisition P&L then work unchanged, and the items become visible to the
purchase team via the "Pending Purchase" view.
"""

from decimal import Decimal
from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum


def auto_create_requisition_for_direct_pi(pi, created_by):
    """Create a requisition mirroring the PI items and link it to the PI."""
    from requisitions.models import Requisition, RequisitionItem

    if pi.requisition_id is not None:
        return pi.requisition

    req = Requisition.objects.create(
        requisition_date=pi.pi_date,
        created_by=created_by,
        remarks=f"Auto-generated for Direct PI {pi.pi_number}",
    )
    for it in pi.items.select_related('product').all():
        ri = RequisitionItem.objects.create(
            requisition=req,
            product=it.product,
            quantity=it.quantity,
            remarks=f"From Direct PI {pi.pi_number}",
        )
        it.requisition_item = ri
        it.save(update_fields=['requisition_item'])

    pi.requisition = req
    pi.save(update_fields=['requisition'])
    return req


def pi_item_procurement_status(pi):
    """Per-item ordered / received / pending quantities (via the PI's requisition)."""
    from purchase_orders.models import PurchaseOrderItem

    rows = []
    req_id = pi.requisition_id
    for it in pi.items.select_related('product').all():
        required = Decimal(str(it.quantity or 0))
        ordered = Decimal('0')
        received = Decimal('0')
        if req_id:
            qs = PurchaseOrderItem.objects.filter(
                po__requisition_id=req_id, product=it.product,
            ).exclude(po__status='CANCELLED')
            ordered = qs.aggregate(t=Sum('quantity'))['t'] or Decimal('0')
            received = qs.filter(is_received=True).aggregate(t=Sum('quantity'))['t'] or Decimal('0')

        pending = required - ordered
        if pending < 0:
            pending = Decimal('0')

        if ordered <= 0:
            status = 'NOT_ORDERED'          # no PO yet — needs buying
        elif ordered < required:
            status = 'PARTIAL'              # some qty on a PO, rest pending
        elif received < required:
            status = 'ORDERED'             # fully on PO, awaiting receipt
        else:
            status = 'RECEIVED'            # fully procured

        rows.append({
            'pi_item_id': str(it.id),
            'product_id': str(it.product_id),
            'item_code': it.product.item_code,
            'item_name': it.product.item_name,
            'unit': it.product.unit,
            'required_qty': float(required),
            'ordered_qty': float(ordered),
            'received_qty': float(received),
            'pending_qty': float(pending),
            'status': status,
        })
    return rows


def pi_procurement_summary(pi):
    """Roll-up of a PI's procurement state for the UI."""
    rows = pi_item_procurement_status(pi)
    total = len(rows)
    not_ordered = sum(1 for r in rows if r['status'] == 'NOT_ORDERED')
    pending_items = sum(1 for r in rows if r['pending_qty'] > 0)
    fully_ordered = sum(1 for r in rows if r['pending_qty'] <= 0 and r['ordered_qty'] > 0)

    if total == 0:
        overall = 'NOT_STARTED'
    elif pending_items == 0:
        overall = 'COMPLETE'
    elif not_ordered == total:
        overall = 'NOT_STARTED'
    else:
        overall = 'PARTIAL'

    return {
        'requisition_id': str(pi.requisition_id) if pi.requisition_id else None,
        'requisition_number': pi.requisition.requisition_number if pi.requisition_id else None,
        'total_items': total,
        'pending_items': pending_items,
        'fully_ordered_items': fully_ordered,
        'overall_status': overall,
        'items': rows,
    }


def notify_purchase_pending(pi, actor):
    """Notify Purchase-permission users that a Direct PI has items to buy."""
    from accounts.models import UserModulePermission
    from signatures.models import Notification

    pending = sum(1 for r in pi_item_procurement_status(pi) if r['pending_qty'] > 0)
    if pending == 0:
        return 0

    user_ids = list(UserModulePermission.objects.filter(
        module='PURCHASE', can_read=True
    ).values_list('user_id', flat=True).distinct())

    ct = ContentType.objects.get_for_model(pi.__class__)
    title = "Items pending purchase"
    msg = (f"Direct PI {pi.pi_number} has {pending} item(s) not yet purchased. "
           f"Raise purchase order(s) to procure them.")

    sent = 0
    for uid in user_ids:
        if actor and uid == actor.id:
            continue
        Notification.objects.create(
            user_id=uid,
            notification_type='PI_ITEMS_NOT_PURCHASED',
            content_type=ct,
            object_id=pi.id,
            actor=actor,
            title=title,
            message=msg,
            action_url=f"/purchase/pending-purchase?pi={pi.id}",
        )
        sent += 1
    return sent
