from rest_framework import viewsets, status, filters, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
from django.db.models import Sum, Q, Count, F
from decimal import Decimal
from datetime import date as date_type, datetime

from .models import PurchasePayment, IncomingPayment
from .serializers import (
    PurchasePaymentSerializer,
    IncomingPaymentSerializer,
    POFinanceSummarySerializer,
    BillFinanceSummarySerializer,
)
from purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from billing.models import Bill, BillPayment
from work_orders.models import WorkOrder
from core.password_confirm import check_password_confirmation


# ═══════════════════════════════════════════════════════════════════════════════
#  OUTGOING PAYMENTS — Vendor payments against Purchase Orders
# ═══════════════════════════════════════════════════════════════════════════════

class PurchaseOrderFinanceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Finance view of Purchase Orders — shows payment status for each PO.

    Endpoints
    ---------
    GET  /api/finance/purchase-orders                       – all POs with payment info
    GET  /api/finance/purchase-orders/{id}                  – single PO with payment info
    GET  /api/finance/purchase-orders/pending_payments      – POs with outstanding balance
    GET  /api/finance/purchase-orders/{id}/purchased_items  – items marked as purchased with prices
    POST /api/finance/purchase-orders/{id}/record_payment   – record outgoing payment  ⚠ password
    GET  /api/finance/purchase-orders/{id}/payment_history  – payment history for a PO
    """

    queryset = PurchaseOrder.objects.all().select_related(
        'requisition', 'vendor', 'created_by'
    ).prefetch_related('items__product', 'purchase_payments__recorded_by')

    serializer_class   = POFinanceSummarySerializer
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields   = ['vendor', 'status']
    search_fields      = ['po_number', 'vendor__vendor_name']
    ordering_fields    = ['po_number', 'po_date', 'total_amount', 'balance']
    ordering           = ['-po_number']

    # ── Purchased items for a PO ─────────────────────────────────────────────

    @action(detail=True, methods=['get'])
    def purchased_items(self, request, pk=None):
        """
        GET /api/finance/purchase-orders/{id}/purchased_items

        Returns all items marked as purchased/received with their prices.
        This is the data that appears in the accounts section showing
        what has been purchased and needs to be paid.
        """
        po = self.get_object()
        purchased = po.items.filter(is_received=True).select_related('product')
        all_items = po.items.all().select_related('product')

        purchased_data = []
        for item in purchased:
            purchased_data.append({
                'item_id':      str(item.id),
                'product_code': item.product.item_code,
                'product_name': item.product.item_name,
                'hsn_code':     item.product.hsn_code,
                'unit':         item.product.unit,
                'quantity':     float(item.quantity),
                'rate':         float(item.rate),
                'amount':       float(item.amount),
            })

        pending_data = []
        for item in all_items.filter(is_received=False):
            pending_data.append({
                'item_id':      str(item.id),
                'product_code': item.product.item_code,
                'product_name': item.product.item_name,
                'quantity':     float(item.quantity),
                'rate':         float(item.rate),
                'amount':       float(item.amount),
            })

        purchased_total = sum(item.amount for item in purchased)

        return Response({
            'po_number':     po.po_number,
            'vendor_name':   po.vendor.vendor_name,
            'po_date':       po.po_date.isoformat(),
            'po_status':     po.status,
            'items_total':   float(po.items_total),
            'freight_cost':  float(po.freight_cost),
            'total_amount':  float(po.total_amount),
            'purchased_items_total': float(purchased_total),
            'purchased_items_count': len(purchased_data),
            'pending_items_count':   len(pending_data),
            'amount_paid':   float(po.amount_paid),
            'balance':       float(po.balance),
            'purchased_items': purchased_data,
            'pending_items':   pending_data,
        })

    # ── Record payment against PO ────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def record_payment(self, request, pk=None):
        """
        Record an outgoing payment against a Purchase Order.

        ⚠️  SENSITIVE ACTION — requires confirm_password in the request body.

        POST /api/finance/purchase-orders/{id}/record_payment
        {
            "confirm_password":  "<your password>",      ← required
            "amount":            50000.00,
            "payment_date":      "2026-03-15",           // optional, default today
            "payment_mode":      "NEFT",                 // CASH/CHEQUE/NEFT/RTGS/IMPS/UPI/OTHER
            "reference_number":  "UTR1234567890",        // optional
            "remarks":           "First instalment"      // optional
        }

        Supports step-by-step (partial) payments.
        """
        password_error = check_password_confirmation(request)
        if password_error:
            return password_error

        po = self.get_object()

        if po.status == 'CANCELLED':
            return Response(
                {'error': 'Cannot record payment on a cancelled PO'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate amount
        raw_amount = request.data.get('amount')
        if raw_amount is None:
            return Response(
                {'error': 'amount is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            amount = Decimal(str(raw_amount))
        except Exception:
            return Response(
                {'error': 'Invalid amount — must be a numeric value'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if amount <= Decimal('0'):
            return Response(
                {'error': 'amount must be greater than 0'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        outstanding = po.total_amount - po.amount_paid
        if amount > outstanding:
            return Response(
                {
                    'error':               'Payment exceeds outstanding balance',
                    'total_amount':        float(po.total_amount),
                    'already_paid':        float(po.amount_paid),
                    'outstanding_balance': float(outstanding),
                    'amount_requested':    float(amount),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Parse date
        raw_date = request.data.get('payment_date')
        if raw_date:
            try:
                payment_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {'error': 'Invalid payment_date — use YYYY-MM-DD'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            payment_date = date_type.today()

        payment_mode  = str(request.data.get('payment_mode', 'NEFT')).upper()
        reference_num = request.data.get('reference_number', '')
        remarks       = request.data.get('remarks', '')

        valid_modes = [m[0] for m in PurchasePayment.PAYMENT_MODE_CHOICES]
        if payment_mode not in valid_modes:
            return Response(
                {'error': f'Invalid payment_mode "{payment_mode}"', 'valid_modes': valid_modes},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Update PO payment tracking
        po.amount_paid = po.amount_paid + amount
        po.balance     = po.total_amount - po.amount_paid
        if po.balance < Decimal('0'):
            po.balance = Decimal('0')
        po.save()

        # Create payment record
        payment_number = po.purchase_payments.count() + 1
        payment = PurchasePayment.objects.create(
            purchase_order   = po,
            payment_number   = payment_number,
            amount           = amount,
            payment_date     = payment_date,
            payment_mode     = payment_mode,
            reference_number = reference_num,
            remarks          = remarks,
            total_paid_after = po.amount_paid,
            balance_after    = po.balance,
            recorded_by      = request.user,
        )

        return Response({
            'message':                  'Payment recorded successfully',
            'payment_number':           payment_number,
            'payment_this_transaction': float(amount),
            'total_paid':               float(po.amount_paid),
            'total_amount':             float(po.total_amount),
            'balance':                  float(po.balance),
            'payment':                  PurchasePaymentSerializer(payment).data,
            'purchase_order':           POFinanceSummarySerializer(po).data,
        })

    # ── Payment history for a PO ─────────────────────────────────────────────

    @action(detail=True, methods=['get'])
    def payment_history(self, request, pk=None):
        """GET /api/finance/purchase-orders/{id}/payment_history"""
        po       = self.get_object()
        payments = po.purchase_payments.select_related('recorded_by').order_by('payment_number')

        return Response({
            'po_number':     po.po_number,
            'vendor_name':   po.vendor.vendor_name,
            'po_date':       po.po_date.isoformat(),
            'total_amount':  float(po.total_amount),
            'total_paid':    float(po.amount_paid),
            'balance':       float(po.balance),
            'status':        po.status,
            'payment_count': payments.count(),
            'payments':      PurchasePaymentSerializer(payments, many=True).data,
        })

    # ── Pending payments ─────────────────────────────────────────────────────

    @action(detail=False, methods=['get'])
    def pending_payments(self, request):
        """
        GET /api/finance/purchase-orders/pending_payments

        All POs with outstanding balance (amount still owed to vendors).
        """
        pending_pos = self.queryset.filter(
            balance__gt=0
        ).exclude(status='CANCELLED')

        total_outstanding = sum(po.balance for po in pending_pos)

        return Response({
            'total_pending_pos':  pending_pos.count(),
            'total_outstanding':  float(total_outstanding),
            'purchase_orders':    POFinanceSummarySerializer(pending_pos, many=True).data,
        })


# ═══════════════════════════════════════════════════════════════════════════════
#  INCOMING PAYMENTS — Client payments against Bills
# ═══════════════════════════════════════════════════════════════════════════════

class BillFinanceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Finance view of Bills — shows payment status for each bill.

    Endpoints
    ---------
    GET  /api/finance/bills                          – all bills with payment info
    GET  /api/finance/bills/{id}                     – single bill with payment info
    GET  /api/finance/bills/pending_payments          – bills with outstanding balance
    POST /api/finance/bills/{id}/record_payment       – record incoming payment  ⚠ password
    GET  /api/finance/bills/{id}/payment_history      – payment history for a bill
    GET  /api/finance/bills/{id}/detailed_summary     – detailed bill summary
    """

    queryset = Bill.objects.all().select_related(
        'work_order', 'created_by'
    ).prefetch_related('items__product', 'incoming_payments__recorded_by')

    serializer_class   = BillFinanceSummarySerializer
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields   = ['status', 'work_order', 'bill_date', 'bill_type']
    search_fields      = ['bill_number', 'client_name', 'work_order__wo_number']
    ordering_fields    = ['bill_date', 'created_at', 'bill_number', 'balance']
    ordering           = ['-bill_number']

    # ── Record incoming payment ──────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def record_payment(self, request, pk=None):
        """
        Record an incoming payment from a client against a Bill.

        ⚠️  SENSITIVE ACTION — requires confirm_password in the request body.

        POST /api/finance/bills/{id}/record_payment
        {
            "confirm_password":  "<your password>",      ← required
            "amount":            45000.00,
            "payment_date":      "2026-02-27",           // optional, default today
            "payment_mode":      "NEFT",                 // CASH/CHEQUE/NEFT/RTGS/IMPS/UPI/OTHER
            "reference_number":  "UTR1234567890",        // optional
            "remarks":           "February instalment"   // optional
        }
        """
        password_error = check_password_confirmation(request)
        if password_error:
            return password_error

        bill = self.get_object()

        if bill.status == 'CANCELLED':
            return Response(
                {'error': 'Cannot record payment on a cancelled bill'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if bill.status == 'PAID':
            return Response(
                {
                    'error':       'Bill is already fully paid',
                    'total_paid':  float(bill.amount_paid),
                    'net_payable': float(bill.net_payable),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw_amount = request.data.get('amount')
        if raw_amount is None:
            return Response(
                {'error': 'amount is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            amount = Decimal(str(raw_amount))
        except Exception:
            return Response(
                {'error': 'Invalid amount — must be a numeric value'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if amount <= Decimal('0'):
            return Response(
                {'error': 'amount must be greater than 0'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        outstanding = bill.net_payable - bill.amount_paid
        if amount > outstanding:
            return Response(
                {
                    'error':               'Payment exceeds outstanding balance',
                    'net_payable':         float(bill.net_payable),
                    'already_paid':        float(bill.amount_paid),
                    'outstanding_balance': float(outstanding),
                    'amount_requested':    float(amount),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw_date     = request.data.get('payment_date')
        payment_mode = str(request.data.get('payment_mode', 'CASH')).upper()
        reference_num = request.data.get('reference_number', '')
        remarks      = request.data.get('remarks', '')

        if raw_date:
            try:
                payment_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {'error': 'Invalid payment_date — use YYYY-MM-DD'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            payment_date = date_type.today()

        valid_modes = [m[0] for m in IncomingPayment.PAYMENT_MODE_CHOICES]
        if payment_mode not in valid_modes:
            return Response(
                {'error': f'Invalid payment_mode "{payment_mode}"', 'valid_modes': valid_modes},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Update bill payment tracking
        bill.amount_paid = bill.amount_paid + amount
        bill.balance     = bill.net_payable - bill.amount_paid
        if bill.balance < Decimal('0'):
            bill.balance = Decimal('0')
        if bill.balance == Decimal('0'):
            bill.status = 'PAID'
        bill.save()

        # Create incoming payment record
        payment_number = bill.incoming_payments.count() + 1
        payment = IncomingPayment.objects.create(
            bill             = bill,
            payment_number   = payment_number,
            amount           = amount,
            payment_date     = payment_date,
            payment_mode     = payment_mode,
            reference_number = reference_num,
            remarks          = remarks,
            total_paid_after = bill.amount_paid,
            balance_after    = bill.balance,
            recorded_by      = request.user,
        )

        # Also create a BillPayment record for backward compatibility
        bill_payment_number = bill.payments.count() + 1
        BillPayment.objects.create(
            bill             = bill,
            payment_number   = bill_payment_number,
            amount           = amount,
            payment_date     = payment_date,
            payment_mode     = payment_mode,
            reference_number = reference_num,
            remarks          = remarks,
            total_paid_after = bill.amount_paid,
            balance_after    = bill.balance,
            recorded_by      = request.user,
        )

        return Response({
            'message':                  'Payment recorded successfully',
            'payment_number':           payment_number,
            'payment_this_transaction': float(amount),
            'total_paid':               float(bill.amount_paid),
            'net_payable':              float(bill.net_payable),
            'balance':                  float(bill.balance),
            'status':                   bill.status,
            'payment':                  IncomingPaymentSerializer(payment).data,
            'bill':                     BillFinanceSummarySerializer(bill).data,
        })

    # ── Payment history ──────────────────────────────────────────────────────

    @action(detail=True, methods=['get'])
    def payment_history(self, request, pk=None):
        """GET /api/finance/bills/{id}/payment_history"""
        bill     = self.get_object()
        payments = bill.incoming_payments.select_related('recorded_by').order_by('payment_number')

        return Response({
            'bill_number':   bill.bill_number,
            'bill_type':     bill.bill_type,
            'client_name':   bill.client_name,
            'wo_number':     bill.work_order.wo_number,
            'bill_date':     bill.bill_date.isoformat(),
            'net_payable':   float(bill.net_payable),
            'total_paid':    float(bill.amount_paid),
            'balance':       float(bill.balance),
            'status':        bill.status,
            'payment_count': payments.count(),
            'payments':      IncomingPaymentSerializer(payments, many=True).data,
        })

    # ── Detailed summary ─────────────────────────────────────────────────────

    @action(detail=True, methods=['get'])
    def detailed_summary(self, request, pk=None):
        """GET /api/finance/bills/{id}/detailed_summary"""
        bill     = self.get_object()
        payments = bill.incoming_payments.select_related('recorded_by').order_by('payment_number')

        items_data = []
        for item in bill.items.all():
            items_data.append({
                'item_code':            item.item_code,
                'item_name':            item.item_name,
                'description':          item.description,
                'hsn_code':             item.hsn_code,
                'ordered_quantity':     float(item.ordered_quantity),
                'previously_delivered': float(item.previously_delivered_quantity),
                'delivered_now':        float(item.delivered_quantity),
                'pending_after':        float(item.pending_quantity),
                'unit':                 item.unit,
                'rate':                 float(item.rate),
                'amount':               float(item.amount),
            })

        return Response({
            'bill_number': bill.bill_number,
            'bill_date':   bill.bill_date,
            'bill_type':   bill.bill_type,
            'wo_number':   bill.work_order.wo_number,
            'client_details': {
                'name':           bill.client_name,
                'contact_person': bill.contact_person,
                'phone':          bill.phone,
                'email':          bill.email,
                'address':        bill.address,
            },
            'items': items_data,
            'financial': {
                'subtotal':         float(bill.subtotal),
                'cgst': {'percentage': float(bill.cgst_percentage), 'amount': float(bill.cgst_amount)},
                'sgst': {'percentage': float(bill.sgst_percentage), 'amount': float(bill.sgst_amount)},
                'igst': {'percentage': float(bill.igst_percentage), 'amount': float(bill.igst_amount)},
                'total_gst':        float(bill.cgst_amount + bill.sgst_amount + bill.igst_amount),
                'total_amount':     float(bill.total_amount),
                'freight_cost':     float(bill.freight_cost),
                'advance_deducted': float(bill.advance_deducted),
                'net_payable':      float(bill.net_payable),
                'amount_paid':      float(bill.amount_paid),
                'balance':          float(bill.balance),
            },
            'payment_summary': {
                'payment_count': payments.count(),
                'total_paid':    float(bill.amount_paid),
                'balance':       float(bill.balance),
                'status':        bill.status,
            },
            'payment_history': IncomingPaymentSerializer(payments, many=True).data,
            'status':  bill.status,
            'remarks': bill.remarks,
        })

    # ── Pending payments ─────────────────────────────────────────────────────

    @action(detail=False, methods=['get'])
    def pending_payments(self, request):
        """
        GET /api/finance/bills/pending_payments

        All bills with outstanding balance (money owed by clients).
        """
        pending_bills = self.queryset.filter(
            balance__gt=0
        ).exclude(status='CANCELLED')

        total_outstanding = sum(b.balance for b in pending_bills)

        return Response({
            'total_pending_bills': pending_bills.count(),
            'total_outstanding':   float(total_outstanding),
            'bills':               BillFinanceSummarySerializer(pending_bills, many=True).data,
        })


# ═══════════════════════════════════════════════════════════════════════════════
#  ALL PAYMENTS — Flat lists of all payment transactions
# ═══════════════════════════════════════════════════════════════════════════════

class AllPurchasePaymentsListView(generics.ListAPIView):
    """
    GET /api/finance/all-purchase-payments

    Flat list of all outgoing payment transactions.
    Filterable by vendor, date range, payment_mode, etc.
    """
    queryset = PurchasePayment.objects.all().select_related(
        'purchase_order__vendor', 'recorded_by'
    )
    serializer_class = PurchasePaymentSerializer
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['payment_mode', 'payment_status', 'purchase_order']
    search_fields    = ['purchase_order__po_number', 'purchase_order__vendor__vendor_name', 'reference_number']
    ordering_fields  = ['payment_date', 'amount', 'created_at']
    ordering         = ['-created_at']


class AllIncomingPaymentsListView(generics.ListAPIView):
    """
    GET /api/finance/all-incoming-payments

    Flat list of all incoming payment transactions.
    Filterable by client, bill, date range, payment_mode, etc.
    """
    queryset = IncomingPayment.objects.all().select_related(
        'bill__work_order', 'recorded_by'
    )
    serializer_class = IncomingPaymentSerializer
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['payment_mode', 'payment_status', 'bill']
    search_fields    = ['bill__bill_number', 'bill__client_name', 'reference_number']
    ordering_fields  = ['payment_date', 'amount', 'created_at']
    ordering         = ['-created_at']


# ═══════════════════════════════════════════════════════════════════════════════
#  FINANCE DASHBOARD — Summary of all incoming and outgoing
# ═══════════════════════════════════════════════════════════════════════════════

class FinanceDashboardView(APIView):
    """
    GET /api/finance/dashboard

    Unified financial dashboard with:
    - Total incoming vs outgoing
    - Outstanding amounts
    - Recent transactions
    - Cash flow summary
    """

    def get(self, request):
        # ── Outgoing (to vendors) ────────────────────────────────────────
        total_po_value = PurchaseOrder.objects.exclude(
            status='CANCELLED'
        ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')

        total_paid_to_vendors = PurchaseOrder.objects.exclude(
            status='CANCELLED'
        ).aggregate(total=Sum('amount_paid'))['total'] or Decimal('0')

        outstanding_to_vendors = PurchaseOrder.objects.exclude(
            status='CANCELLED'
        ).filter(balance__gt=0).aggregate(total=Sum('balance'))['total'] or Decimal('0')

        pending_po_count = PurchaseOrder.objects.exclude(
            status='CANCELLED'
        ).filter(balance__gt=0).count()

        # ── Incoming (from clients) ──────────────────────────────────────
        total_bill_value = Bill.objects.exclude(
            status='CANCELLED'
        ).aggregate(total=Sum('net_payable'))['total'] or Decimal('0')

        total_received_from_clients = Bill.objects.exclude(
            status='CANCELLED'
        ).aggregate(total=Sum('amount_paid'))['total'] or Decimal('0')

        outstanding_from_clients = Bill.objects.exclude(
            status='CANCELLED'
        ).filter(balance__gt=0).aggregate(total=Sum('balance'))['total'] or Decimal('0')

        pending_bill_count = Bill.objects.exclude(
            status='CANCELLED'
        ).filter(balance__gt=0).count()

        # ── Recent transactions ──────────────────────────────────────────
        recent_outgoing = PurchasePayment.objects.select_related(
            'purchase_order__vendor', 'recorded_by'
        ).order_by('-created_at')[:10]

        recent_incoming = IncomingPayment.objects.select_related(
            'bill__work_order', 'recorded_by'
        ).order_by('-created_at')[:10]

        # ── Purchase items overview ──────────────────────────────────────
        total_po_items = PurchaseOrderItem.objects.exclude(
            po__status='CANCELLED'
        ).count()

        purchased_items = PurchaseOrderItem.objects.filter(
            is_received=True
        ).exclude(po__status='CANCELLED').count()

        purchased_items_value = PurchaseOrderItem.objects.filter(
            is_received=True
        ).exclude(po__status='CANCELLED').aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')

        return Response({
            'outgoing': {
                'label':       'Payments to Vendors',
                'total_value': float(total_po_value),
                'total_paid':  float(total_paid_to_vendors),
                'outstanding': float(outstanding_to_vendors),
                'pending_count': pending_po_count,
            },
            'incoming': {
                'label':       'Payments from Clients',
                'total_value': float(total_bill_value),
                'total_received': float(total_received_from_clients),
                'outstanding':    float(outstanding_from_clients),
                'pending_count':  pending_bill_count,
            },
            'cash_flow': {
                'total_inflow':  float(total_received_from_clients),
                'total_outflow': float(total_paid_to_vendors),
                'net_flow':      float(total_received_from_clients - total_paid_to_vendors),
            },
            'purchase_items': {
                'total_items':       total_po_items,
                'purchased_items':   purchased_items,
                'pending_items':     total_po_items - purchased_items,
                'purchased_value':   float(purchased_items_value),
            },
            'recent_outgoing': PurchasePaymentSerializer(recent_outgoing, many=True).data,
            'recent_incoming': IncomingPaymentSerializer(recent_incoming, many=True).data,
        })
