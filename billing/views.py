from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
from decimal import Decimal
from datetime import date as date_type, datetime

from core.permissions import SalesModulePermission
from .models import PIBill, PIBillPayment
from .serializers import PIBillSerializer, PIBillCreateSerializer, PIBillPaymentSerializer
from core.password_confirm import check_password_confirmation
from audit_logs.models import AuditLog


class PIBillViewSet(viewsets.ModelViewSet):
    permission_classes = [SalesModulePermission]
    queryset = PIBill.objects.all().select_related(
        'proforma_invoice', 'created_by'
    ).prefetch_related('pi_bill_items__product')

    filter_backends  = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'proforma_invoice', 'bill_date', 'bill_type']
    search_fields    = ['bill_number', 'client_name', 'proforma_invoice__pi_number']
    ordering_fields  = ['bill_date', 'created_at', 'bill_number']
    ordering         = ['-bill_number']

    def get_serializer_class(self):
        if self.action == 'create':
            return PIBillCreateSerializer
        return PIBillSerializer

    def perform_create(self, serializer):
        bill = serializer.save(created_by=self.request.user)
        AuditLog.log(self.request.user, 'CREATE', bill, {
            'bill_number': bill.bill_number,
            'pi_number': bill.proforma_invoice.pi_number,
            'client_name': bill.client_name,
            'currency': bill.currency,
            'total_amount': str(bill.total_amount),
            'net_payable': str(bill.net_payable),
        })

    def destroy(self, request, *args, **kwargs):
        return Response(
            {'error': 'PI Bills cannot be deleted. Use the cancel endpoint.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def mark_paid(self, request, pk=None):
        password_error = check_password_confirmation(request)
        if password_error:
            return password_error

        bill = self.get_object()

        if bill.status == 'CANCELLED':
            return Response({'error': 'Cannot record payment on a cancelled bill'}, status=status.HTTP_400_BAD_REQUEST)
        if bill.status == 'PAID':
            return Response({'error': 'Bill is already fully paid'}, status=status.HTTP_400_BAD_REQUEST)

        raw_amount = request.data.get('amount_paid')
        if raw_amount is None:
            return Response({'error': 'amount_paid is required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            amount_paid_now = Decimal(str(raw_amount))
        except Exception:
            return Response({'error': 'Invalid amount'}, status=status.HTTP_400_BAD_REQUEST)

        if amount_paid_now <= Decimal('0'):
            return Response({'error': 'amount_paid must be greater than 0'}, status=status.HTTP_400_BAD_REQUEST)

        outstanding = bill.net_payable - bill.amount_paid
        if amount_paid_now > outstanding:
            return Response({
                'error': 'Payment exceeds outstanding balance',
                'outstanding_balance': float(outstanding),
            }, status=status.HTTP_400_BAD_REQUEST)

        raw_date = request.data.get('payment_date')
        if raw_date:
            try:
                datetime.strptime(raw_date, '%Y-%m-%d').date()
            except ValueError:
                return Response({'error': 'Invalid payment_date — use YYYY-MM-DD'}, status=status.HTTP_400_BAD_REQUEST)

        payment_mode = request.data.get('payment_mode', 'NEFT')
        reference_number = request.data.get('reference_number', '')
        remarks = request.data.get('remarks', '')

        bill.amount_paid = bill.amount_paid + amount_paid_now
        bill.balance = bill.net_payable - bill.amount_paid
        if bill.balance <= Decimal('0'):
            bill.balance = Decimal('0')
            bill.status = 'PAID'
        bill.save()

        last_payment = bill.payments.order_by('-payment_number').first()
        payment_number = (last_payment.payment_number + 1) if last_payment else 1

        payment_date_value = date_type.today()
        if raw_date:
            payment_date_value = datetime.strptime(raw_date, '%Y-%m-%d').date()

        payment = PIBillPayment.objects.create(
            pi_bill=bill,
            payment_number=payment_number,
            amount=amount_paid_now,
            payment_date=payment_date_value,
            payment_mode=payment_mode,
            reference_number=reference_number,
            remarks=remarks,
            total_paid_after=bill.amount_paid,
            balance_after=bill.balance,
            recorded_by=request.user,
        )

        AuditLog.log(request.user, 'CREATE', payment, {
            'action': 'PI_BILL_PAYMENT',
            'bill_number': bill.bill_number,
            'payment_number': payment_number,
            'amount': str(amount_paid_now),
            'payment_mode': payment_mode,
            'total_paid_after': str(bill.amount_paid),
            'balance_after': str(bill.balance),
        })

        return Response({
            'message': 'Payment recorded successfully',
            'payment_number': payment_number,
            'amount_paid_now': float(amount_paid_now),
            'total_paid': float(bill.amount_paid),
            'net_payable': float(bill.net_payable),
            'balance': float(bill.balance),
            'status': bill.status,
            'bill': PIBillSerializer(bill).data,
        })

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        password_error = check_password_confirmation(request)
        if password_error:
            return password_error

        bill = self.get_object()
        if bill.status == 'CANCELLED':
            return Response({'error': 'Bill is already cancelled'}, status=status.HTTP_400_BAD_REQUEST)
        if bill.status == 'PAID':
            return Response({'error': 'Cannot cancel a paid bill'}, status=status.HTTP_400_BAD_REQUEST)

        bill.status = 'CANCELLED'
        bill.save()

        AuditLog.log(request.user, 'STATUS_CHANGE', bill, {
            'action': 'PI_BILL_CANCEL',
            'bill_number': bill.bill_number,
            'old_status': 'GENERATED',
            'new_status': 'CANCELLED',
        })

        return Response({
            'message': 'PI Bill cancelled successfully',
            'bill': PIBillSerializer(bill).data,
        })

    @action(detail=True, methods=['get'])
    def payment_history(self, request, pk=None):
        bill = self.get_object()
        payments = bill.payments.all().order_by('payment_number')
        return Response({
            'bill_number': bill.bill_number,
            'currency': bill.currency,
            'conversion_rate': float(bill.conversion_rate) if bill.conversion_rate else None,
            'net_payable': float(bill.net_payable),
            'total_paid': float(bill.amount_paid),
            'balance': float(bill.balance),
            'status': bill.status,
            'total_payments': payments.count(),
            'payments': PIBillPaymentSerializer(payments, many=True).data,
        })

    @action(detail=False, methods=['get'])
    def by_pi(self, request):
        pi_id = request.query_params.get('proforma_invoice')
        if not pi_id:
            return Response({'error': 'proforma_invoice parameter is required'}, status=status.HTTP_400_BAD_REQUEST)
        bills = self.queryset.filter(proforma_invoice_id=pi_id)
        return Response({
            'total_bills': bills.count(),
            'bills': PIBillSerializer(bills, many=True).data,
        })

    @action(detail=False, methods=['get'])
    def pending_payment(self, request):
        pending = self.queryset.filter(balance__gt=0).exclude(status='CANCELLED')
        total_balance = sum(b.balance for b in pending)
        return Response({
            'total_pending_bills': pending.count(),
            'total_balance': float(total_balance),
            'bills': PIBillSerializer(pending, many=True).data,
        })
