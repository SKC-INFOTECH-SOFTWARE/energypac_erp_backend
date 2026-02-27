from rest_framework import viewsets, status, filters, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
from decimal import Decimal
from datetime import date as date_type, datetime

from .models import Bill, BillItem, BillPayment
from .serializers import (
    BillSerializer,
    BillCreateSerializer,
    BillItemSerializer,
    BillPaymentSerializer,
    StockValidationSerializer,
)


class BillViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Bill CRUD operations

    Endpoints
    ---------
    Standard CRUD:
        GET    /api/bills                           – list all bills
        POST   /api/bills                           – create bill (auto deducts stock)
        GET    /api/bills/{id}                      – retrieve bill (includes payments[])
        PUT    /api/bills/{id}                      – full update
        PATCH  /api/bills/{id}                      – partial update

    Custom actions:
        POST   /api/bills/validate_stock            – pre-creation stock check
        POST   /api/bills/{id}/mark_paid            – record a payment (partial or full)
        GET    /api/bills/{id}/payment_history      – full payment history  ← NEW
        GET    /api/bills/{id}/detailed_summary     – detail + payment breakdown
        POST   /api/bills/{id}/cancel               – cancel bill & restore stock
        GET    /api/bills/by_work_order             – all bills for a work order
        GET    /api/bills/pending_payment           – all bills with outstanding balance
    """
    queryset = Bill.objects.all().select_related(
        'work_order', 'created_by'
    ).prefetch_related('items__product', 'payments__recorded_by')

    filter_backends  = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'work_order', 'bill_date']
    search_fields    = ['bill_number', 'client_name', 'work_order__wo_number']
    ordering_fields  = ['bill_date', 'created_at', 'bill_number']
    ordering         = ['-bill_number']

    def get_serializer_class(self):
        if self.action == 'create':
            return BillCreateSerializer
        if self.action == 'validate_stock':
            return StockValidationSerializer
        return BillSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def destroy(self, request, *args, **kwargs):
        return Response(
            {
                'error':   'Bills cannot be deleted',
                'message': 'Use the cancel endpoint to cancel a bill',
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Stock validation
    # ──────────────────────────────────────────────────────────────────────────

    @action(detail=False, methods=['post'])
    def validate_stock(self, request):
        """
        Validate stock before bill generation.

        POST /api/bills/validate_stock
        {
            "work_order": "uuid",
            "items": [{"work_order_item": "uuid", "delivered_quantity": 10}]
        }
        """
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            return Response({'stock_available': True, 'message': 'All items available for billing'})
        except serializers.ValidationError as e:
            if 'stock_validation_failed' in e.detail:
                return Response(
                    {'stock_available': False, 'issues': e.detail['issues']},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)

    # ──────────────────────────────────────────────────────────────────────────
    # Payment recording
    # ──────────────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def mark_paid(self, request, pk=None):
        """
        Record a payment (cumulative — safe for partial payments).
        Every call creates a BillPayment row and adds to the running total.

        POST /api/bills/{id}/mark_paid
        {
            "amount_paid":      45000.00,          // REQUIRED
            "payment_date":     "2026-02-27",      // optional – defaults to today
            "payment_mode":     "NEFT",            // optional – CASH/CHEQUE/NEFT/RTGS/IMPS/UPI/OTHER
            "reference_number": "UTR1234567890",   // optional
            "remarks":          "February instalment"  // optional
        }

        Example (net_payable = 1,00,000):
            1st call  amount_paid=40,000  →  total=40,000   balance=60,000  GENERATED
            2nd call  amount_paid=60,000  →  total=1,00,000 balance=0       PAID
        """
        bill = self.get_object()

        # ── Guard rails ────────────────────────────────────────────────────────
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

        # ── Parse & validate amount ────────────────────────────────────────────
        raw_amount = request.data.get('amount_paid')
        if raw_amount is None:
            return Response(
                {'error': 'amount_paid is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            amount_paid_now = Decimal(str(raw_amount))
        except Exception:
            return Response(
                {'error': 'Invalid amount — must be a numeric value'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if amount_paid_now <= Decimal('0'):
            return Response(
                {'error': 'amount_paid must be greater than 0'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        outstanding = bill.net_payable - bill.amount_paid
        if amount_paid_now > outstanding:
            return Response(
                {
                    'error':               'Payment exceeds outstanding balance',
                    'net_payable':         float(bill.net_payable),
                    'already_paid':        float(bill.amount_paid),
                    'outstanding_balance': float(outstanding),
                    'amount_requested':    float(amount_paid_now),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Parse optional fields ─────────────────────────────────────────────
        raw_date      = request.data.get('payment_date')
        payment_mode  = str(request.data.get('payment_mode', 'CASH')).upper()
        reference_num = request.data.get('reference_number', '')
        remarks       = request.data.get('remarks', '')

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

        valid_modes = [m[0] for m in BillPayment.PAYMENT_MODE_CHOICES]
        if payment_mode not in valid_modes:
            return Response(
                {'error': f'Invalid payment_mode "{payment_mode}"', 'valid_modes': valid_modes},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Apply payment (ACCUMULATE — never replace) ────────────────────────
        bill.amount_paid = bill.amount_paid + amount_paid_now
        bill.balance     = bill.net_payable - bill.amount_paid

        if bill.balance < Decimal('0'):
            bill.balance = Decimal('0')          # float-dust guard

        if bill.balance == Decimal('0'):
            bill.status = 'PAID'

        bill.save()

        # ── Create payment history row ─────────────────────────────────────────
        # Count AFTER save so the row we are about to create gets the right number
        payment_number = bill.payments.count() + 1

        payment = BillPayment.objects.create(
            bill             = bill,
            payment_number   = payment_number,
            amount           = amount_paid_now,
            payment_date     = payment_date,
            payment_mode     = payment_mode,
            reference_number = reference_num,
            remarks          = remarks,
            total_paid_after = bill.amount_paid,
            balance_after    = bill.balance,
            recorded_by      = request.user,
        )

        # ── Response ───────────────────────────────────────────────────────────
        return Response({
            'message':                  'Payment recorded successfully',
            'payment_number':           payment_number,
            'payment_this_transaction': float(amount_paid_now),
            'total_paid':               float(bill.amount_paid),
            'net_payable':              float(bill.net_payable),
            'balance':                  float(bill.balance),
            'status':                   bill.status,
            'payment':                  BillPaymentSerializer(payment).data,
            'bill':                     BillSerializer(bill).data,
        })

    # ──────────────────────────────────────────────────────────────────────────
    # Payment history  ← NEW
    # ──────────────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['get'])
    def payment_history(self, request, pk=None):
        """
        Full payment history for a bill — every partial and final payment.

        GET /api/bills/{id}/payment_history

        Response:
        {
          "bill_number":   "BILL/2026/0001",
          "client_name":   "Acme Corp",
          "wo_number":     "WO/2026/0012",
          "bill_date":     "2026-01-15",
          "net_payable":   100000.00,
          "total_paid":    100000.00,
          "balance":       0.00,
          "status":        "PAID",
          "payment_count": 2,
          "payments": [
            {
              "payment_number":       1,
              "amount":               40000.00,
              "payment_date":         "2026-02-10",
              "payment_mode":         "NEFT",
              "payment_mode_display": "NEFT",
              "reference_number":     "UTR123456",
              "remarks":              "First instalment",
              "total_paid_after":     40000.00,
              "balance_after":        60000.00,
              "recorded_by_name":     "Rahul Sharma",
              "created_at":           "2026-02-10T14:30:00"
            },
            {
              "payment_number":       2,
              "amount":               60000.00,
              "payment_date":         "2026-02-25",
              "payment_mode":         "RTGS",
              "payment_mode_display": "RTGS",
              "reference_number":     "UTR789012",
              "remarks":              "Final payment",
              "total_paid_after":     100000.00,
              "balance_after":        0.00,
              "recorded_by_name":     "Rahul Sharma",
              "created_at":           "2026-02-25T10:15:00"
            }
          ]
        }
        """
        bill     = self.get_object()
        payments = bill.payments.select_related('recorded_by').order_by('payment_number')

        return Response({
            'bill_number':   bill.bill_number,
            'client_name':   bill.client_name,
            'wo_number':     bill.work_order.wo_number,
            'bill_date':     bill.bill_date.isoformat(),
            'net_payable':   float(bill.net_payable),
            'total_paid':    float(bill.amount_paid),
            'balance':       float(bill.balance),
            'status':        bill.status,
            'payment_count': payments.count(),
            'payments':      BillPaymentSerializer(payments, many=True).data,
        })

    # ──────────────────────────────────────────────────────────────────────────
    # Detailed summary (existing — now includes payment_history)
    # ──────────────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['get'])
    def detailed_summary(self, request, pk=None):
        """
        Complete bill detail: items + financials + full payment history.

        GET /api/bills/{id}/detailed_summary
        """
        bill     = self.get_object()
        payments = bill.payments.select_related('recorded_by').order_by('payment_number')

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
            'payment_history': BillPaymentSerializer(payments, many=True).data,
            'status':  bill.status,
            'remarks': bill.remarks,
        })

    # ──────────────────────────────────────────────────────────────────────────
    # Cancel
    # ──────────────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def cancel(self, request, pk=None):
        """
        Cancel bill and restore stock.

        POST /api/bills/{id}/cancel
        """
        bill = self.get_object()

        if bill.status == 'CANCELLED':
            return Response({'error': 'Bill is already cancelled'}, status=status.HTTP_400_BAD_REQUEST)
        if bill.status == 'PAID':
            return Response({'error': 'Cannot cancel a paid bill'}, status=status.HTTP_400_BAD_REQUEST)

        bill.restore_stock()
        bill.status = 'CANCELLED'
        bill.save()

        return Response({
            'message': 'Bill cancelled successfully. Stock has been restored.',
            'bill':    BillSerializer(bill).data,
        })

    # ──────────────────────────────────────────────────────────────────────────
    # Utility list endpoints
    # ──────────────────────────────────────────────────────────────────────────

    @action(detail=False, methods=['get'])
    def by_work_order(self, request):
        """GET /api/bills/by_work_order?work_order={wo_id}"""
        wo_id = request.query_params.get('work_order')
        if not wo_id:
            return Response({'error': 'work_order parameter is required'}, status=status.HTTP_400_BAD_REQUEST)

        bills = self.queryset.filter(work_order_id=wo_id)
        return Response({'total_bills': bills.count(), 'bills': BillSerializer(bills, many=True).data})

    @action(detail=False, methods=['get'])
    def pending_payment(self, request):
        """GET /api/bills/pending_payment"""
        pending_bills = self.queryset.filter(balance__gt=0).exclude(status='CANCELLED')
        total_balance = sum(b.balance for b in pending_bills)
        return Response({
            'total_pending_bills': pending_bills.count(),
            'total_balance':       float(total_balance),
            'bills':               BillSerializer(pending_bills, many=True).data,
        })
