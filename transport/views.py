from rest_framework import viewsets, status, filters, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
from django.db.models import Sum, Count, F, Q
from decimal import Decimal
from datetime import date

from core.permissions import TransportModulePermission, TransportOrFinancePermission, FinanceModulePermission
from core.password_confirm import check_password_confirmation
from audit_logs.models import AuditLog
from .models import (
    TransportEntry, TransportCostItem,
    Transporter, TransportConsignmentItem, TransportPayment,
)
from .serializers import (
    TransportEntrySerializer,
    TransportEntryCreateSerializer,
    TransportEntryUpdateSerializer,
    TransporterSerializer,
    TransportPaymentSerializer,
)
from purchase_orders.models import PurchaseOrder
from sales.models import ProformaInvoice


def _to_inr(amount, currency, rate):
    """Convert a PO/PI amount to INR using the stored conversion rate.
    Transport/freight is already INR, so only the trade-side amount needs converting."""
    amt = amount or Decimal('0')
    if currency and currency != 'INR' and rate:
        return amt * rate
    return amt


class TransporterViewSet(viewsets.ModelViewSet):
    """Transporter master + per-transporter ledger."""
    permission_classes = [TransportModulePermission]
    serializer_class = TransporterSerializer
    queryset = Transporter.objects.select_related('created_by').all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active']
    search_fields = ['transporter_code', 'name', 'phone', 'gst_number', 'contact_person']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        AuditLog.log(self.request.user, 'CREATE', obj, {'name': obj.name, 'code': obj.transporter_code})

    @action(detail=True, methods=['get'])
    def ledger(self, request, pk=None):
        """Full ledger for one transporter: every entry with billed / paid / balance,
        split by BUY (we pay) and SELL (we recover from client)."""
        transporter = self.get_object()
        entries = transporter.transport_entries.exclude(
            status='CANCELLED'
        ).select_related('purchase_order__vendor', 'proforma_invoice').order_by('-created_at')

        rows = []
        buy_billed = buy_paid = sell_billed = sell_paid = Decimal('0')
        for e in entries:
            direction = e.direction
            ref = e.purchase_order.po_number if e.purchase_order else (
                e.proforma_invoice.pi_number if e.proforma_invoice else '—'
            )
            rows.append({
                'transport_number': e.transport_number,
                'direction': direction,
                'reference': ref,
                'dispatch_date': e.dispatch_date,
                'status': e.status,
                'payment_status': e.payment_status,
                'total_cost': float(e.total_cost),
                'amount_paid': float(e.amount_paid),
                'balance': float(e.balance),
            })
            if direction == 'BUY':
                buy_billed += e.total_cost
                buy_paid += e.amount_paid
            elif direction == 'SELL':
                sell_billed += e.total_cost
                sell_paid += e.amount_paid

        return Response({
            'transporter': TransporterSerializer(transporter).data,
            'summary': {
                'buy_billed': float(buy_billed),
                'buy_paid': float(buy_paid),
                'buy_balance': float(buy_billed - buy_paid),
                'sell_billed': float(sell_billed),
                'sell_paid': float(sell_paid),
                'sell_balance': float(sell_billed - sell_paid),
            },
            'entries': rows,
        })


class TransportEntryViewSet(viewsets.ModelViewSet):
    permission_classes = [TransportModulePermission]
    queryset = TransportEntry.objects.all().select_related(
        'purchase_order__vendor', 'proforma_invoice', 'transporter', 'created_by'
    ).prefetch_related('cost_items', 'consignment_items__product', 'payments')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = [
        'purchase_order', 'proforma_invoice', 'transporter',
        'status', 'payment_status', 'dispatch_date',
    ]
    search_fields = [
        'transport_number', 'transporter_name', 'vehicle_number',
        'purchase_order__po_number', 'purchase_order__vendor__vendor_name',
        'proforma_invoice__pi_number',
    ]
    ordering_fields = ['created_at', 'dispatch_date', 'total_cost']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return TransportEntryCreateSerializer
        if self.action in ('update', 'partial_update'):
            return TransportEntryUpdateSerializer
        return TransportEntrySerializer

    def get_permissions(self):
        # Recording a payment is strictly a Finance-department action.
        if self.action == 'record_payment':
            return [FinanceModulePermission()]
        # Read-only payment history & the transport note are needed by BOTH
        # the Finance payments page and the Transport entry list.
        if self.action in ('payment_history', 'transport_note'):
            return [TransportOrFinancePermission()]
        return super().get_permissions()

    def perform_create(self, serializer):
        entry = serializer.save(created_by=self.request.user)
        ref = entry.purchase_order.po_number if entry.purchase_order else (
            entry.proforma_invoice.pi_number if entry.proforma_invoice else 'N/A'
        )
        AuditLog.log(self.request.user, 'CREATE', entry, {
            'transport_number': entry.transport_number,
            'reference': ref,
            'transporter': entry.transporter_name,
            'total_cost': str(entry.total_cost),
        })
        from signatures.notifications import notify_module
        notify_module(
            'TRANSPORT',
            notification_type='TRANSPORT_CREATED',
            title='New Transport Entry',
            message=f'Transport {entry.transport_number} ({ref}) via {entry.transporter_name}.',
            obj=entry,
            actor=self.request.user,
            action_url='/transport',
        )

    def perform_update(self, serializer):
        entry = self.get_object()
        if entry.status == 'DELIVERED':
            from rest_framework.exceptions import ValidationError
            raise ValidationError("Cannot edit a delivered transport entry.")
        old_values = {
            'transporter': entry.transporter_name,
            'status': entry.status,
            'total_cost': str(entry.total_cost),
        }
        entry = serializer.save()
        AuditLog.log(self.request.user, 'UPDATE', entry, {
            'old': old_values,
            'new': {
                'transporter': entry.transporter_name,
                'status': entry.status,
                'total_cost': str(entry.total_cost),
            },
        })

    def destroy(self, request, *args, **kwargs):
        return Response(
            {'error': 'Transport entries cannot be deleted (audit trail)'},
            status=status.HTTP_403_FORBIDDEN,
        )

    # ── Landed Cost per PO ───────────────────────────────────────────────
    @action(detail=False, methods=['get'])
    def landed_cost(self, request):
        po_id = request.query_params.get('purchase_order')
        if not po_id:
            return Response(
                {'error': 'purchase_order parameter is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            po = PurchaseOrder.objects.prefetch_related(
                'items__product', 'transport_entries__cost_items'
            ).get(id=po_id)
        except PurchaseOrder.DoesNotExist:
            return Response({'error': 'Purchase order not found'}, status=status.HTTP_404_NOT_FOUND)

        total_transport = sum(
            entry.total_cost for entry in po.transport_entries.all()
        )
        # convert PO amounts to INR (freight is already INR)
        items_total = _to_inr(po.items_total or Decimal('0'), po.currency, po.conversion_rate)

        items_data = []
        for item in po.items.all():
            amount_inr = _to_inr(item.amount, po.currency, po.conversion_rate)
            rate_inr = _to_inr(item.rate, po.currency, po.conversion_rate)
            if items_total > 0:
                value_pct = (amount_inr / items_total) * Decimal('100')
                allocated = (amount_inr / items_total) * total_transport
            else:
                value_pct = Decimal('0')
                allocated = Decimal('0')

            landed = amount_inr + allocated
            landed_rate = landed / item.quantity if item.quantity > 0 else Decimal('0')

            items_data.append({
                'item_id': str(item.id),
                'product_code': item.product.item_code,
                'product_name': item.product.item_name,
                'quantity': float(item.quantity),
                'unit': item.product.unit,
                'purchase_rate': round(float(rate_inr), 2),
                'purchase_amount': round(float(amount_inr), 2),
                'value_percentage': round(float(value_pct), 2),
                'allocated_transport': round(float(allocated), 2),
                'landed_cost': round(float(landed), 2),
                'landed_rate_per_unit': round(float(landed_rate), 2),
            })

        transport_entries = []
        for entry in po.transport_entries.all():
            transport_entries.append({
                'transport_number': entry.transport_number,
                'transporter_name': entry.transporter_name,
                'dispatch_date': entry.dispatch_date,
                'status': entry.status,
                'total_cost': float(entry.total_cost),
                'cost_breakdown': {
                    ci.get_cost_type_display(): float(ci.amount)
                    for ci in entry.cost_items.all()
                },
            })

        po_total_inr = _to_inr(po.total_amount, po.currency, po.conversion_rate)
        gst_inr = _to_inr(
            po.cgst_amount + po.sgst_amount + po.igst_amount, po.currency, po.conversion_rate
        )
        return Response({
            'po_number': po.po_number,
            'vendor_name': po.vendor.vendor_name,
            'currency': 'INR',
            'original_currency': po.currency,
            'conversion_rate': float(po.conversion_rate) if po.conversion_rate else 1,
            'items_total': round(float(items_total), 2),
            'gst_total': round(float(gst_inr), 2),
            'po_total_amount': round(float(po_total_inr), 2),
            'total_transport_cost': float(total_transport),
            'grand_total_with_transport': round(float(po_total_inr + total_transport), 2),
            'transport_entries': transport_entries,
            'items': items_data,
        })

    # ── Transport entries by PI ──────────────────────────────────────────
    @action(detail=False, methods=['get'])
    def by_pi(self, request):
        pi_id = request.query_params.get('proforma_invoice')
        if not pi_id:
            return Response(
                {'error': 'proforma_invoice parameter is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        entries = self.queryset.filter(proforma_invoice_id=pi_id)
        serializer = TransportEntrySerializer(entries, many=True)
        return Response(serializer.data)

    # ── Landed Cost per PI ───────────────────────────────────────────────
    @action(detail=False, methods=['get'])
    def landed_cost_pi(self, request):
        pi_id = request.query_params.get('proforma_invoice')
        if not pi_id:
            return Response({'error': 'proforma_invoice parameter is required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            pi = ProformaInvoice.objects.prefetch_related(
                'items__product', 'transport_entries__cost_items'
            ).get(id=pi_id)
        except ProformaInvoice.DoesNotExist:
            return Response({'error': 'Proforma Invoice not found'}, status=status.HTTP_404_NOT_FOUND)

        total_transport = sum(e.total_cost for e in pi.transport_entries.all())
        # convert PI amounts to INR (freight is already INR)
        items_total = _to_inr(pi.grand_total or Decimal('0'), pi.currency, pi.conversion_rate)

        items_data = []
        for item in pi.items.all():
            amount_inr = _to_inr(item.amount, pi.currency, pi.conversion_rate)
            unit_price_inr = _to_inr(item.unit_price, pi.currency, pi.conversion_rate)
            if items_total > 0:
                value_pct = (amount_inr / items_total) * Decimal('100')
                allocated = (amount_inr / items_total) * total_transport
            else:
                value_pct = Decimal('0')
                allocated = Decimal('0')

            items_data.append({
                'item_id': str(item.id),
                'product_name': item.product.item_name,
                'quantity': float(item.quantity),
                'unit_price': round(float(unit_price_inr), 2),
                'amount': round(float(amount_inr), 2),
                'value_percentage': round(float(value_pct), 2),
                'allocated_transport': round(float(allocated), 2),
                'total_with_transport': round(float(amount_inr + allocated), 2),
            })

        grand_total_inr = _to_inr(pi.grand_total, pi.currency, pi.conversion_rate)
        return Response({
            'pi_number': pi.pi_number,
            'currency': 'INR',
            'original_currency': pi.currency,
            'conversion_rate': float(pi.conversion_rate) if pi.conversion_rate else 1,
            'grand_total': round(float(grand_total_inr), 2),
            'total_transport_cost': float(total_transport),
            'grand_total_with_transport': round(float(grand_total_inr + total_transport), 2),
            'items': items_data,
        })

    # ── Transport entries by PO ──────────────────────────────────────────
    @action(detail=False, methods=['get'])
    def by_po(self, request):
        po_id = request.query_params.get('purchase_order')
        if not po_id:
            return Response(
                {'error': 'purchase_order parameter is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        entries = self.queryset.filter(purchase_order_id=po_id)
        serializer = TransportEntrySerializer(entries, many=True)
        return Response(serializer.data)

    # ── Mark delivered ───────────────────────────────────────────────────
    @action(detail=True, methods=['post'])
    def mark_delivered(self, request, pk=None):
        entry = self.get_object()
        if entry.status == 'CANCELLED':
            return Response(
                {'error': 'Cannot mark cancelled entry as delivered'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from django.utils import timezone
        from datetime import date
        entry.status = 'DELIVERED'
        entry.actual_delivery_date = entry.actual_delivery_date or date.today()
        entry.save(update_fields=['status', 'actual_delivery_date'])

        AuditLog.log(request.user, 'UPDATE', entry, {
            'action': 'MARK_DELIVERED',
            'actual_delivery_date': str(entry.actual_delivery_date),
        })
        return Response(TransportEntrySerializer(entry).data)

    # ── Cancel a shipment (password-confirmed) ───────────────────────────
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        error = check_password_confirmation(request)
        if error:
            return error

        entry = self.get_object()
        if entry.status == 'CANCELLED':
            return Response({'error': 'Shipment is already cancelled.'}, status=status.HTTP_400_BAD_REQUEST)
        if entry.status == 'DELIVERED':
            return Response({'error': 'A delivered shipment cannot be cancelled.'}, status=status.HTTP_400_BAD_REQUEST)
        if (entry.amount_paid or Decimal('0')) > 0:
            return Response(
                {'error': 'This shipment has recorded payments and cannot be cancelled.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        entry.status = 'CANCELLED'
        entry.recalc_balance()
        entry.save(update_fields=['status', 'balance', 'payment_status'])
        AuditLog.log(request.user, 'UPDATE', entry, {
            'action': 'CANCEL_SHIPMENT',
            'transport_number': entry.transport_number,
        })
        return Response(TransportEntrySerializer(entry).data)

    # ── Record a transporter payment (BUY: we pay / SELL: client pays us) ─
    @action(detail=True, methods=['post'])
    def record_payment(self, request, pk=None):
        error = check_password_confirmation(request)
        if error:
            return error

        entry = self.get_object()
        if entry.status == 'CANCELLED':
            return Response(
                {'error': 'Cannot record a payment on a cancelled transport entry.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            amount = Decimal(str(request.data.get('amount')))
        except (TypeError, ValueError, ArithmeticError):
            return Response({'error': 'A valid amount is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if amount <= 0:
            return Response({'error': 'Amount must be greater than zero.'}, status=status.HTTP_400_BAD_REQUEST)

        if amount > entry.balance:
            return Response(
                {'error': f'Amount {amount} exceeds outstanding balance {entry.balance}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payment_date = request.data.get('payment_date') or date.today()
        payment_mode = request.data.get('payment_mode', 'NEFT')
        reference_number = request.data.get('reference_number', '')
        remarks = request.data.get('remarks', '')

        with transaction.atomic():
            entry.amount_paid = (entry.amount_paid or Decimal('0')) + amount
            entry.recalc_balance()
            entry.save(update_fields=['amount_paid', 'balance', 'payment_status'])

            payment = TransportPayment.objects.create(
                transport_entry=entry,
                amount=amount,
                payment_date=payment_date,
                payment_mode=payment_mode,
                reference_number=reference_number,
                remarks=remarks,
                total_paid_after=entry.amount_paid,
                balance_after=entry.balance,
                recorded_by=request.user,
            )

        AuditLog.log(request.user, 'UPDATE', entry, {
            'action': 'TRANSPORT_PAYMENT',
            'direction': entry.direction,
            'payment_number': payment.payment_number,
            'amount': str(amount),
            'balance_after': str(entry.balance),
        })
        return Response({
            'message': 'Payment recorded.',
            'payment': TransportPaymentSerializer(payment).data,
            'entry': TransportEntrySerializer(entry).data,
        })

    @action(detail=True, methods=['get'])
    def payment_history(self, request, pk=None):
        entry = self.get_object()
        payments = entry.payments.select_related('recorded_by').all()
        return Response({
            'transport_number': entry.transport_number,
            'direction': entry.direction,
            'total_cost': float(entry.total_cost),
            'amount_paid': float(entry.amount_paid),
            'balance': float(entry.balance),
            'payment_status': entry.payment_status,
            'payments': TransportPaymentSerializer(payments, many=True).data,
        })

    # ── Dispatch tracker for one PO or PI (ordered vs shipped vs pending) ──
    @action(detail=False, methods=['get'])
    def dispatch_tracker(self, request):
        po_id = request.query_params.get('purchase_order')
        pi_id = request.query_params.get('proforma_invoice')
        if not po_id and not pi_id:
            return Response(
                {'error': 'purchase_order or proforma_invoice parameter is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # annotate each line with shipped qty (excluding cancelled shipments) in one query
        shipped_agg = Sum(
            'consignment_items__quantity',
            filter=~Q(consignment_items__transport_entry__status='CANCELLED'),
        )

        if po_id:
            if not PurchaseOrder.objects.filter(id=po_id).exists():
                return Response({'error': 'Purchase order not found'}, status=status.HTTP_404_NOT_FOUND)
            po = PurchaseOrder.objects.get(id=po_id)
            source_items = po.items.select_related('product').annotate(shipped_qty_agg=shipped_agg)
            ref_number = po.po_number
            kind = 'PO'
        else:
            if not ProformaInvoice.objects.filter(id=pi_id).exists():
                return Response({'error': 'Proforma Invoice not found'}, status=status.HTTP_404_NOT_FOUND)
            pi = ProformaInvoice.objects.get(id=pi_id)
            source_items = pi.items.select_related('product').annotate(shipped_qty_agg=shipped_agg)
            ref_number = pi.pi_number
            kind = 'PI'

        rows = []
        all_full = True
        any_shipped = False
        for item in source_items:
            shipped = item.shipped_qty_agg or Decimal('0')
            ordered = item.quantity or Decimal('0')
            pending = ordered - shipped
            if pending < 0:
                pending = Decimal('0')
            if shipped > 0:
                any_shipped = True
            if pending > 0:
                all_full = False
            rows.append({
                'item_id': str(item.id),
                'product_name': item.product.item_name,
                'product_code': item.product.item_code,
                'unit': item.product.unit,
                'ordered_qty': float(ordered),
                'shipped_qty': float(shipped),
                'pending_qty': float(pending),
                'fully_shipped': pending <= 0,
            })

        if not any_shipped:
            dispatch_state = 'NOT_DISPATCHED'
        elif all_full:
            dispatch_state = 'FULLY_DISPATCHED'
        else:
            dispatch_state = 'PARTIALLY_DISPATCHED'

        return Response({
            'kind': kind,
            'reference': ref_number,
            'dispatch_state': dispatch_state,
            'items': rows,
        })

    # ── Pending-dispatch board (POs/PIs with items still to ship) ─────────
    @action(detail=False, methods=['get'])
    def pending_dispatch(self, request):
        side = request.query_params.get('side', 'BUY')  # BUY = POs, SELL = PIs

        shipped_agg = Sum(
            'consignment_items__quantity',
            filter=~Q(consignment_items__transport_entry__status='CANCELLED'),
        )

        def build(source_qs, kind):
            board = []
            for obj in source_qs:
                # one query per order (annotated) instead of one per line item
                items = list(obj.items.annotate(shipped_qty_agg=shipped_agg))
                total_ordered = total_shipped = Decimal('0')
                pending_lines = 0
                for item in items:
                    shipped = item.shipped_qty_agg or Decimal('0')
                    ordered = item.quantity or Decimal('0')
                    total_ordered += ordered
                    total_shipped += min(shipped, ordered)
                    if shipped < ordered:
                        pending_lines += 1
                if pending_lines == 0:
                    continue
                if kind == 'PO':
                    board.append({
                        'kind': 'PO', 'id': str(obj.id), 'reference': obj.po_number,
                        'party': obj.vendor.vendor_name, 'currency': obj.currency,
                        'total_ordered_qty': float(total_ordered),
                        'total_shipped_qty': float(total_shipped),
                        'pending_lines': pending_lines,
                        'total_lines': len(items),
                    })
                else:
                    board.append({
                        'kind': 'PI', 'id': str(obj.id), 'reference': obj.pi_number,
                        'party': (obj.consignee.split('\n')[0].strip() if obj.consignee else '—'),
                        'currency': obj.currency,
                        'total_ordered_qty': float(total_ordered),
                        'total_shipped_qty': float(total_shipped),
                        'pending_lines': pending_lines,
                        'total_lines': len(items),
                    })
            return board

        if side == 'SELL':
            qs = ProformaInvoice.objects.exclude(status='CANCELLED').order_by('-pi_date')
            board = build(qs, 'PI')
        else:
            qs = PurchaseOrder.objects.exclude(status='CANCELLED').select_related('vendor').order_by('-created_at')
            board = build(qs, 'PO')

        return Response({'side': side, 'count': len(board), 'pending': board})

    # ── Transport Note Sheet data (for client-requested PDF) ──────────────
    @action(detail=True, methods=['get'])
    def transport_note(self, request, pk=None):
        entry = self.get_object()
        po = entry.purchase_order
        pi = entry.proforma_invoice

        # Transport / freight is always recorded in INR, regardless of the
        # PO/PI trade currency.
        currency = 'INR'
        if po:
            party_label = 'Vendor'
            party_name = po.vendor.vendor_name
            ref_label = 'Purchase Order'
            ref_number = po.po_number
        elif pi:
            party_label = 'Client'
            party_name = pi.consignee.split('\n')[0].strip() if pi.consignee else '—'
            ref_label = 'Proforma Invoice'
            ref_number = pi.pi_number
        else:
            party_label = party_name = ref_label = ref_number = '—'

        consignment = []
        for ci in entry.consignment_items.select_related('product').all():
            consignment.append({
                'product_name': ci.product.item_name,
                'product_code': ci.product.item_code,
                'unit': ci.product.unit,
                'quantity': float(ci.quantity),
                'remarks': ci.remarks,
            })

        cost_items = [
            {
                'cost_type': ci.get_cost_type_display(),
                'description': ci.description,
                'amount': float(ci.amount),
            }
            for ci in entry.cost_items.all()
        ]

        return Response({
            'transport_number': entry.transport_number,
            'direction': entry.direction,
            'party_label': party_label,
            'party_name': party_name,
            'ref_label': ref_label,
            'ref_number': ref_number,
            'currency': currency,
            'transporter_name': entry.transporter_name,
            'transporter_contact': entry.transporter_contact,
            'vehicle_number': entry.vehicle_number,
            'driver_name': entry.driver_name,
            'driver_contact': entry.driver_contact,
            'lr_number': entry.lr_number,
            'invoice_reference': entry.invoice_reference,
            'dispatch_date': entry.dispatch_date,
            'expected_delivery_date': entry.expected_delivery_date,
            'actual_delivery_date': entry.actual_delivery_date,
            'dispatch_from': entry.dispatch_from,
            'dispatch_to': entry.dispatch_to,
            'status': entry.get_status_display(),
            'remarks': entry.remarks,
            'consignment_items': consignment,
            'cost_items': cost_items,
            'total_cost': float(entry.total_cost),
            'amount_paid': float(entry.amount_paid),
            'balance': float(entry.balance),
            'payment_status': entry.get_payment_status_display(),
            'generated_on': date.today(),
        })


# ═════════════════════════════════════════════════════════════════════════════
# REPORTS
# ═════════════════════════════════════════════════════════════════════════════

class TransportCostByPOReportView(APIView):
    """Transport cost summary grouped by Purchase Order."""
    permission_classes = [TransportModulePermission]

    def get(self, request):
        entries = TransportEntry.objects.exclude(
            status='CANCELLED'
        ).values(
            'purchase_order__id',
            'purchase_order__po_number',
            'purchase_order__vendor__vendor_name',
            'purchase_order__currency',
            'purchase_order__conversion_rate',
            'purchase_order__total_amount',
        ).annotate(
            shipment_count=Count('id'),
            total_transport_cost=Sum('total_cost'),
        ).order_by('-total_transport_cost')

        results = []
        for row in entries:
            # PO amount converted to INR so it lines up with INR freight
            po_amount = _to_inr(
                row['purchase_order__total_amount'] or Decimal('0'),
                row['purchase_order__currency'],
                row['purchase_order__conversion_rate'],
            )
            transport = row['total_transport_cost'] or Decimal('0')
            results.append({
                'po_id': str(row['purchase_order__id']),
                'po_number': row['purchase_order__po_number'],
                'vendor_name': row['purchase_order__vendor__vendor_name'],
                'currency': 'INR',
                'original_currency': row['purchase_order__currency'],
                'po_amount': round(float(po_amount), 2),
                'shipment_count': row['shipment_count'],
                'total_transport_cost': float(transport),
                'grand_total': round(float(po_amount + transport), 2),
                'transport_percentage': round(float(
                    (transport / po_amount * 100) if po_amount > 0 else 0
                ), 2),
            })

        total_po = sum(r['po_amount'] for r in results)
        total_transport = sum(r['total_transport_cost'] for r in results)

        return Response({
            'total_pos': len(results),
            'total_po_value': total_po,
            'total_transport_cost': total_transport,
            'overall_transport_percentage': round(
                (total_transport / total_po * 100) if total_po > 0 else 0, 2
            ),
            'purchase_orders': results,
        })


class TransportCostByVendorReportView(APIView):
    """Transport cost summary grouped by Vendor."""
    permission_classes = [TransportModulePermission]

    def get(self, request):
        entries = TransportEntry.objects.exclude(
            status='CANCELLED'
        ).values(
            'purchase_order__vendor__id',
            'purchase_order__vendor__vendor_name',
            'purchase_order__vendor__vendor_code',
        ).annotate(
            po_count=Count('purchase_order', distinct=True),
            shipment_count=Count('id'),
            total_transport_cost=Sum('total_cost'),
        ).order_by('-total_transport_cost')

        results = []
        for row in entries:
            results.append({
                'vendor_id': str(row['purchase_order__vendor__id']),
                'vendor_name': row['purchase_order__vendor__vendor_name'],
                'vendor_code': row['purchase_order__vendor__vendor_code'],
                'po_count': row['po_count'],
                'shipment_count': row['shipment_count'],
                'total_transport_cost': float(row['total_transport_cost'] or 0),
            })

        return Response({
            'total_vendors': len(results),
            'total_transport_cost': sum(r['total_transport_cost'] for r in results),
            'vendors': results,
        })


class TransportCostBreakdownReportView(APIView):
    """Transport cost breakdown by cost type across all POs."""
    permission_classes = [TransportModulePermission]

    def get(self, request):
        breakdown = TransportCostItem.objects.filter(
            transport_entry__status__in=['PENDING', 'IN_TRANSIT', 'DELIVERED'],
        ).values('cost_type').annotate(
            total_amount=Sum('amount'),
            entry_count=Count('id'),
        ).order_by('-total_amount')

        cost_type_map = dict(TransportCostItem.COST_TYPE_CHOICES)
        results = []
        grand_total = Decimal('0')
        for row in breakdown:
            amount = row['total_amount'] or Decimal('0')
            grand_total += amount
            results.append({
                'cost_type': row['cost_type'],
                'cost_type_display': cost_type_map.get(row['cost_type'], row['cost_type']),
                'total_amount': float(amount),
                'entry_count': row['entry_count'],
            })

        for r in results:
            r['percentage'] = round(
                (r['total_amount'] / float(grand_total) * 100) if grand_total > 0 else 0, 2
            )

        return Response({
            'grand_total': float(grand_total),
            'breakdown': results,
        })


class LandedCostReportView(APIView):
    """Landed cost report — item-wise across all POs with transport allocation."""
    permission_classes = [TransportModulePermission]

    def get(self, request):
        vendor_id = request.query_params.get('vendor')
        po_status = request.query_params.get('status')

        pos = PurchaseOrder.objects.exclude(
            status='CANCELLED'
        ).select_related('vendor').prefetch_related(
            'items__product', 'transport_entries'
        )
        if vendor_id:
            pos = pos.filter(vendor_id=vendor_id)
        if po_status:
            pos = pos.filter(status=po_status)

        items_report = []
        for po in pos:
            total_transport = sum(e.total_cost for e in po.transport_entries.all())
            # convert PO amounts to INR (freight is already INR)
            items_total = _to_inr(po.items_total or Decimal('0'), po.currency, po.conversion_rate)

            for item in po.items.all():
                amount_inr = _to_inr(item.amount, po.currency, po.conversion_rate)
                rate_inr = _to_inr(item.rate, po.currency, po.conversion_rate)
                if items_total > 0:
                    allocated = (amount_inr / items_total) * total_transport
                else:
                    allocated = Decimal('0')

                landed = amount_inr + allocated
                landed_rate = landed / item.quantity if item.quantity > 0 else Decimal('0')

                items_report.append({
                    'po_number': po.po_number,
                    'vendor_name': po.vendor.vendor_name,
                    'currency': 'INR',
                    'original_currency': po.currency,
                    'product_code': item.product.item_code,
                    'product_name': item.product.item_name,
                    'quantity': float(item.quantity),
                    'unit': item.product.unit,
                    'purchase_rate': round(float(rate_inr), 2),
                    'purchase_amount': round(float(amount_inr), 2),
                    'allocated_transport': round(float(allocated), 2),
                    'landed_cost': round(float(landed), 2),
                    'landed_rate_per_unit': round(float(landed_rate), 2),
                    'is_received': item.is_received,
                })

        total_purchase = sum(i['purchase_amount'] for i in items_report)
        total_transport_all = sum(i['allocated_transport'] for i in items_report)
        total_landed = sum(i['landed_cost'] for i in items_report)

        return Response({
            'total_items': len(items_report),
            'total_purchase_value': round(total_purchase, 2),
            'total_transport_cost': round(total_transport_all, 2),
            'total_landed_cost': round(total_landed, 2),
            'items': items_report,
        })


class TransportDashboardView(APIView):
    """Transport module dashboard stats."""
    permission_classes = [TransportModulePermission]

    def get(self, request):
        all_entries = TransportEntry.objects.exclude(status='CANCELLED')

        total_entries = all_entries.count()
        pending = all_entries.filter(status='PENDING').count()
        in_transit = all_entries.filter(status='IN_TRANSIT').count()
        delivered = all_entries.filter(status='DELIVERED').count()

        total_cost = all_entries.aggregate(total=Sum('total_cost'))['total'] or Decimal('0')

        cost_by_type = TransportCostItem.objects.filter(
            transport_entry__status__in=['PENDING', 'IN_TRANSIT', 'DELIVERED'],
        ).values('cost_type').annotate(
            total=Sum('amount')
        ).order_by('-total')

        cost_type_map = dict(TransportCostItem.COST_TYPE_CHOICES)

        recent = TransportEntry.objects.exclude(
            status='CANCELLED'
        ).select_related(
            'purchase_order__vendor', 'created_by'
        ).order_by('-created_at')[:10]

        return Response({
            'summary': {
                'total_entries': total_entries,
                'pending': pending,
                'in_transit': in_transit,
                'delivered': delivered,
                'total_cost': float(total_cost),
            },
            'cost_by_type': [
                {
                    'cost_type': row['cost_type'],
                    'label': cost_type_map.get(row['cost_type'], row['cost_type']),
                    'total': float(row['total'] or 0),
                }
                for row in cost_by_type
            ],
            'recent_entries': TransportEntrySerializer(recent, many=True).data,
        })


class TransportPaymentsFinanceView(APIView):
    """
    Finance-facing view of transporter payments — both sides.

    BUY side  = freight we OWE transporters on Purchase Orders (a payable).
    SELL side = freight we RECOVER from clients on Proforma Invoices (a receivable).

    Drives the Finance > Transport Payments page and feeds revenue/cost tracking.
    Read-only data is visible to BOTH Transport and Finance; recording a payment
    (separate endpoint) stays Finance-only.
    """
    permission_classes = [TransportOrFinancePermission]

    def get(self, request):
        side = request.query_params.get('side')  # BUY | SELL | None(all)

        entries = TransportEntry.objects.exclude(status='CANCELLED').select_related(
            'purchase_order__vendor', 'proforma_invoice', 'transporter',
        ).prefetch_related('payments')

        if side == 'BUY':
            entries = entries.filter(purchase_order__isnull=False)
        elif side == 'SELL':
            entries = entries.filter(proforma_invoice__isnull=False)

        buy = {'billed': Decimal('0'), 'paid': Decimal('0'), 'balance': Decimal('0'), 'count': 0}
        sell = {'billed': Decimal('0'), 'paid': Decimal('0'), 'balance': Decimal('0'), 'count': 0}
        rows = []
        for e in entries.order_by('-created_at'):
            direction = e.direction
            ref = e.purchase_order.po_number if e.purchase_order else (
                e.proforma_invoice.pi_number if e.proforma_invoice else '—'
            )
            party = (e.purchase_order.vendor.vendor_name if e.purchase_order else
                     (e.proforma_invoice.consignee.split('\n')[0].strip()
                      if e.proforma_invoice and e.proforma_invoice.consignee else '—'))
            bucket = buy if direction == 'BUY' else sell
            bucket['billed'] += e.total_cost
            bucket['paid'] += e.amount_paid
            bucket['balance'] += e.balance
            bucket['count'] += 1
            rows.append({
                'id': str(e.id),
                'transport_number': e.transport_number,
                'direction': direction,
                'reference': ref,
                'party': party,
                'transporter_name': e.transporter_name,
                'dispatch_date': e.dispatch_date,
                'status': e.status,
                'payment_status': e.payment_status,
                'total_cost': float(e.total_cost),
                'amount_paid': float(e.amount_paid),
                'balance': float(e.balance),
                'payment_count': e.payments.count(),
            })

        def fmt(b):
            return {
                'billed': float(b['billed']), 'paid': float(b['paid']),
                'balance': float(b['balance']), 'count': b['count'],
            }

        return Response({
            'side': side or 'ALL',
            'buy': fmt(buy),
            'sell': fmt(sell),
            'net_cost_to_company': float(buy['billed'] - sell['billed']),
            'entries': rows,
        })
