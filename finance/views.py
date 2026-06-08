from rest_framework import viewsets, status, filters, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
from django.db.models import Sum, Q, Count, F
from decimal import Decimal
from datetime import date as date_type, datetime, timedelta

from core.permissions import FinanceModulePermission
from .models import PurchasePayment, PIPayment, AdvancePayment
from .serializers import (
    PurchasePaymentSerializer,
    PIPaymentSerializer,
    PIFinanceSummarySerializer,
    POFinanceSummarySerializer,
    AdvancePaymentSerializer,
)
from purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from sales.models import ProformaInvoice, ProformaInvoiceItem
from transport.models import TransportEntry
from requisitions.models import Requisition
from inventory.models import Product
from core.password_confirm import check_password_confirmation
from audit_logs.models import AuditLog


# ═════════════════════════════════════════════════════════════════════════════
# PO Finance — Payments to vendors
# ═════════════════════════════════════════════════════════════════════════════

class PurchaseOrderFinanceViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [FinanceModulePermission]
    queryset = PurchaseOrder.objects.all().select_related(
        'requisition', 'vendor', 'created_by'
    ).prefetch_related('items__product', 'purchase_payments__recorded_by')

    serializer_class   = POFinanceSummarySerializer
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields   = ['vendor', 'status']
    search_fields      = ['po_number', 'vendor__vendor_name']
    ordering_fields    = ['po_number', 'po_date', 'total_amount', 'balance']
    ordering           = ['-po_number']

    @action(detail=True, methods=['get'])
    def purchased_items(self, request, pk=None):
        po = self.get_object()
        purchased = po.items.filter(is_received=True).select_related('product')
        all_items = po.items.all().select_related('product')

        purchased_data = [
            {
                'item_id': str(i.id),
                'product_code': i.product.item_code,
                'product_name': i.product.item_name,
                'hsn_code': i.product.hsn_code,
                'unit': i.product.unit,
                'quantity': float(i.quantity),
                'rate': float(i.rate),
                'amount': float(i.amount),
            }
            for i in purchased
        ]

        pending_data = [
            {
                'item_id': str(i.id),
                'product_code': i.product.item_code,
                'product_name': i.product.item_name,
                'hsn_code': i.product.hsn_code,
                'unit': i.product.unit,
                'quantity': float(i.quantity),
                'rate': float(i.rate),
                'amount': float(i.amount),
            }
            for i in all_items.filter(is_received=False)
        ]

        purchased_total = sum(i.amount for i in purchased)
        computed_balance = max(po.total_amount - po.amount_paid, Decimal('0'))

        return Response({
            'po_number': po.po_number,
            'vendor_name': po.vendor.vendor_name,
            'po_date': po.po_date.isoformat(),
            'po_status': po.status,
            'items_total': float(po.items_total),
            'total_amount': float(po.total_amount),
            'purchased_items_total': float(purchased_total),
            'purchased_items_count': len(purchased_data),
            'pending_items_count': len(pending_data),
            'amount_paid': float(po.amount_paid),
            'balance': float(computed_balance),
            'purchased_items': purchased_data,
            'pending_items': pending_data,
        })

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def record_payment(self, request, pk=None):
        password_error = check_password_confirmation(request)
        if password_error:
            return password_error

        po = self.get_object()

        if po.status == 'CANCELLED':
            return Response(
                {'error': 'Cannot record payment on a cancelled PO'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw_amount = request.data.get('amount')
        if raw_amount is None:
            return Response({'error': 'amount is required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            amount = Decimal(str(raw_amount))
        except Exception:
            return Response({'error': 'Invalid amount'}, status=status.HTTP_400_BAD_REQUEST)

        if amount <= Decimal('0'):
            return Response({'error': 'amount must be greater than 0'}, status=status.HTTP_400_BAD_REQUEST)

        outstanding = max(po.total_amount - po.amount_paid, Decimal('0'))
        if amount > outstanding:
            return Response(
                {
                    'error': 'Payment exceeds outstanding balance',
                    'total_amount': float(po.total_amount),
                    'already_paid': float(po.amount_paid),
                    'outstanding_balance': float(outstanding),
                    'amount_requested': float(amount),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw_date = request.data.get('payment_date')
        if raw_date:
            try:
                payment_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
            except ValueError:
                return Response({'error': 'Invalid payment_date — use YYYY-MM-DD'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            payment_date = date_type.today()

        payment_mode = str(request.data.get('payment_mode', 'NEFT')).upper()
        reference_num = request.data.get('reference_number', '')
        remarks = request.data.get('remarks', '')

        valid_modes = [m[0] for m in PurchasePayment.PAYMENT_MODE_CHOICES]
        if payment_mode not in valid_modes:
            return Response(
                {'error': f'Invalid payment_mode "{payment_mode}"', 'valid_modes': valid_modes},
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_amount_paid = po.amount_paid + amount
        new_balance = max(po.total_amount - new_amount_paid, Decimal('0'))

        update_kwargs = {'amount_paid': new_amount_paid, 'balance': new_balance}
        if new_balance == Decimal('0'):
            update_kwargs['status'] = 'COMPLETED'

        PurchaseOrder.objects.filter(pk=po.pk).update(**update_kwargs)
        po.refresh_from_db()

        payment_number = po.purchase_payments.count() + 1
        payment = PurchasePayment.objects.create(
            purchase_order=po,
            payment_number=payment_number,
            amount=amount,
            payment_date=payment_date,
            payment_mode=payment_mode,
            reference_number=reference_num,
            remarks=remarks,
            total_paid_after=po.amount_paid,
            balance_after=po.balance,
            recorded_by=request.user,
        )

        AuditLog.log(request.user, 'CREATE', payment, {
            'action': 'PO_PAYMENT',
            'po_number': po.po_number,
            'payment_number': payment_number,
            'amount': str(amount),
            'payment_mode': payment_mode,
            'total_paid_after': str(po.amount_paid),
            'balance_after': str(po.balance),
        })

        return Response({
            'message': 'Payment recorded successfully',
            'payment_number': payment_number,
            'payment_this_transaction': float(amount),
            'total_paid': float(po.amount_paid),
            'total_amount': float(po.total_amount),
            'balance': float(po.balance),
            'po_status': po.status,
            'payment': PurchasePaymentSerializer(payment).data,
            'purchase_order': POFinanceSummarySerializer(po).data,
        })

    @action(detail=True, methods=['get'])
    def payment_history(self, request, pk=None):
        po = self.get_object()
        payments = po.purchase_payments.select_related('recorded_by').order_by('payment_number')
        computed_balance = max(po.total_amount - po.amount_paid, Decimal('0'))

        return Response({
            'po_number': po.po_number,
            'vendor_name': po.vendor.vendor_name,
            'po_date': po.po_date.isoformat(),
            'currency': po.currency or 'INR',
            'conversion_rate': float(po.conversion_rate) if po.conversion_rate else None,
            'total_amount': float(po.total_amount),
            'total_paid': float(po.amount_paid),
            'balance': float(computed_balance),
            'status': po.status,
            'payment_count': payments.count(),
            'payments': PurchasePaymentSerializer(payments, many=True).data,
        })

    @action(detail=False, methods=['get'])
    def pending_payments(self, request):
        pending_pos = self.queryset.filter(
            total_amount__gt=F('amount_paid')
        ).exclude(status='CANCELLED')

        total_outstanding = sum(
            max(po.total_amount - po.amount_paid, Decimal('0'))
            for po in pending_pos
        )

        return Response({
            'total_pending_pos': pending_pos.count(),
            'total_outstanding': float(total_outstanding),
            'purchase_orders': POFinanceSummarySerializer(pending_pos, many=True).data,
        })

    @action(detail=False, methods=['get'])
    def overdue(self, request):
        today = date_type.today()
        overdue_pos = self.queryset.filter(
            payment_due_date__lt=today,
            total_amount__gt=F('amount_paid'),
        ).exclude(status='CANCELLED')

        results = []
        for po in overdue_pos:
            days_overdue = (today - po.payment_due_date).days
            results.append({
                'po_id': str(po.id),
                'po_number': po.po_number,
                'vendor_name': po.vendor.vendor_name,
                'total_amount': float(po.total_amount),
                'amount_paid': float(po.amount_paid),
                'balance': float(max(po.total_amount - po.amount_paid, Decimal('0'))),
                'payment_due_date': po.payment_due_date.isoformat(),
                'days_overdue': days_overdue,
            })

        return Response({
            'total_overdue': len(results),
            'total_overdue_amount': sum(r['balance'] for r in results),
            'purchase_orders': results,
        })


# ═════════════════════════════════════════════════════════════════════════════
# PI Finance — Client payments against Proforma Invoices
# ═════════════════════════════════════════════════════════════════════════════

class PIFinanceViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [FinanceModulePermission]
    queryset = ProformaInvoice.objects.all().select_related(
        'requisition', 'created_by'
    ).prefetch_related('items__product', 'pi_payments__recorded_by')

    serializer_class = PIFinanceSummarySerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'currency', 'requisition']
    search_fields = ['pi_number', 'requisition__requisition_number']
    ordering = ['-pi_number']

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def record_payment(self, request, pk=None):
        password_error = check_password_confirmation(request)
        if password_error:
            return password_error

        pi = self.get_object()

        if pi.status == 'CANCELLED':
            return Response({'error': 'Cannot record payment on a cancelled PI'}, status=status.HTTP_400_BAD_REQUEST)

        raw_amount = request.data.get('amount')
        if raw_amount is None:
            return Response({'error': 'amount is required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            amount = Decimal(str(raw_amount))
        except Exception:
            return Response({'error': 'Invalid amount'}, status=status.HTTP_400_BAD_REQUEST)

        if amount <= Decimal('0'):
            return Response({'error': 'amount must be greater than 0'}, status=status.HTTP_400_BAD_REQUEST)

        outstanding = max(pi.grand_total - pi.amount_received, Decimal('0'))
        if amount > outstanding:
            return Response({
                'error': 'Payment exceeds outstanding balance',
                'grand_total': float(pi.grand_total),
                'already_received': float(pi.amount_received),
                'outstanding_balance': float(outstanding),
            }, status=status.HTTP_400_BAD_REQUEST)

        raw_date = request.data.get('payment_date')
        if raw_date:
            try:
                payment_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
            except ValueError:
                return Response({'error': 'Invalid payment_date'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            payment_date = date_type.today()

        payment_mode = str(request.data.get('payment_mode', 'TT')).upper()
        reference_num = request.data.get('reference_number', '')
        remarks = request.data.get('remarks', '')

        valid_modes = [m[0] for m in PIPayment.PAYMENT_MODE_CHOICES]
        if payment_mode not in valid_modes:
            return Response({'error': 'Invalid payment_mode', 'valid_modes': valid_modes}, status=status.HTTP_400_BAD_REQUEST)

        new_amount_received = pi.amount_received + amount
        new_balance = max(pi.grand_total - new_amount_received, Decimal('0'))

        update_kwargs = {'amount_received': new_amount_received, 'balance': new_balance}
        if new_balance == Decimal('0'):
            update_kwargs['status'] = 'ACCEPTED'

        ProformaInvoice.objects.filter(pk=pi.pk).update(**update_kwargs)
        pi.refresh_from_db()

        payment_number = pi.pi_payments.count() + 1
        payment = PIPayment.objects.create(
            proforma_invoice=pi,
            payment_number=payment_number,
            amount=amount,
            payment_date=payment_date,
            payment_mode=payment_mode,
            reference_number=reference_num,
            remarks=remarks,
            total_paid_after=pi.amount_received,
            balance_after=pi.balance,
            recorded_by=request.user,
        )

        AuditLog.log(request.user, 'CREATE', payment, {
            'action': 'PI_PAYMENT',
            'pi_number': pi.pi_number,
            'payment_number': payment_number,
            'amount': str(amount),
            'currency': pi.currency,
            'payment_mode': payment_mode,
            'total_received_after': str(pi.amount_received),
            'balance_after': str(pi.balance),
        })

        return Response({
            'message': 'Payment recorded successfully',
            'payment_number': payment_number,
            'payment_this_transaction': float(amount),
            'total_received': float(pi.amount_received),
            'grand_total': float(pi.grand_total),
            'balance': float(pi.balance),
            'pi_status': pi.status,
            'payment': PIPaymentSerializer(payment).data,
            'proforma_invoice': PIFinanceSummarySerializer(pi).data,
        })

    @action(detail=True, methods=['get'])
    def payment_history(self, request, pk=None):
        pi = self.get_object()
        payments = pi.pi_payments.select_related('recorded_by').order_by('payment_number')

        return Response({
            'pi_number': pi.pi_number,
            'currency': pi.currency,
            'conversion_rate': float(pi.conversion_rate) if pi.conversion_rate else None,
            'grand_total': float(pi.grand_total),
            'total_received': float(pi.amount_received),
            'balance': float(max(pi.grand_total - pi.amount_received, Decimal('0'))),
            'status': pi.status,
            'payment_count': payments.count(),
            'payments': PIPaymentSerializer(payments, many=True).data,
        })

    @action(detail=False, methods=['get'])
    def pending_payments(self, request):
        pending_pis = self.queryset.filter(
            grand_total__gt=F('amount_received')
        ).exclude(status='CANCELLED')

        total_outstanding = sum(
            max(pi.grand_total - pi.amount_received, Decimal('0'))
            for pi in pending_pis
        )

        return Response({
            'total_pending_pis': pending_pis.count(),
            'total_outstanding': float(total_outstanding),
            'proforma_invoices': PIFinanceSummarySerializer(pending_pis, many=True).data,
        })

    @action(detail=False, methods=['get'])
    def overdue(self, request):
        today = date_type.today()
        overdue_pis = self.queryset.filter(
            payment_due_date__lt=today,
            grand_total__gt=F('amount_received'),
        ).exclude(status='CANCELLED')

        results = []
        for pi in overdue_pis:
            days_overdue = (today - pi.payment_due_date).days
            results.append({
                'pi_id': str(pi.id),
                'pi_number': pi.pi_number,
                'requisition_number': pi.requisition.requisition_number if pi.requisition else 'STOCK SALE',
                'currency': pi.currency,
                'grand_total': float(pi.grand_total),
                'amount_received': float(pi.amount_received),
                'balance': float(max(pi.grand_total - pi.amount_received, Decimal('0'))),
                'payment_due_date': pi.payment_due_date.isoformat(),
                'days_overdue': days_overdue,
            })

        return Response({
            'total_overdue': len(results),
            'total_overdue_amount': sum(r['balance'] for r in results),
            'proforma_invoices': results,
        })


# ═════════════════════════════════════════════════════════════════════════════
# Flat Payment Lists
# ═════════════════════════════════════════════════════════════════════════════

class AllPurchasePaymentsListView(generics.ListAPIView):
    permission_classes = [FinanceModulePermission]
    queryset = PurchasePayment.objects.all().select_related('purchase_order__vendor', 'recorded_by')
    serializer_class = PurchasePaymentSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['payment_mode', 'payment_status', 'purchase_order']
    search_fields = ['purchase_order__po_number', 'purchase_order__vendor__vendor_name', 'reference_number']
    ordering = ['-created_at']


class AllPIPaymentsListView(generics.ListAPIView):
    permission_classes = [FinanceModulePermission]
    queryset = PIPayment.objects.all().select_related('proforma_invoice__requisition', 'recorded_by')
    serializer_class = PIPaymentSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['payment_mode', 'payment_status', 'proforma_invoice']
    search_fields = ['proforma_invoice__pi_number', 'reference_number']
    ordering = ['-created_at']


# ═════════════════════════════════════════════════════════════════════════════
# Advance Payments
# ═════════════════════════════════════════════════════════════════════════════

class AdvancePaymentViewSet(viewsets.ModelViewSet):
    permission_classes = [FinanceModulePermission]
    queryset = AdvancePayment.objects.all().select_related('proforma_invoice', 'recorded_by')
    serializer_class = AdvancePaymentSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'currency', 'proforma_invoice']
    search_fields = ['advance_number', 'client_name', 'proforma_invoice__pi_number']
    ordering = ['-created_at']

    def perform_create(self, serializer):
        advance = serializer.save(recorded_by=self.request.user)
        AuditLog.log(self.request.user, 'CREATE', advance, {
            'action': 'ADVANCE_PAYMENT',
            'advance_number': advance.advance_number,
            'pi_number': advance.proforma_invoice.pi_number,
            'amount': str(advance.amount),
            'currency': advance.currency,
            'client_name': advance.client_name,
        })

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def adjust(self, request, pk=None):
        """Use part or all of an advance against a PI."""
        advance = self.get_object()

        if advance.status != 'ACTIVE':
            return Response({'error': 'Advance is not active'}, status=status.HTTP_400_BAD_REQUEST)

        raw_amount = request.data.get('amount')
        if raw_amount is None:
            return Response({'error': 'amount is required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            amount = Decimal(str(raw_amount))
        except Exception:
            return Response({'error': 'Invalid amount'}, status=status.HTTP_400_BAD_REQUEST)

        if amount <= Decimal('0'):
            return Response({'error': 'amount must be greater than 0'}, status=status.HTTP_400_BAD_REQUEST)

        if amount > advance.remaining:
            return Response({
                'error': 'Amount exceeds remaining advance',
                'remaining': float(advance.remaining),
            }, status=status.HTTP_400_BAD_REQUEST)

        new_used = advance.amount_used + amount
        new_remaining = advance.amount - new_used
        new_status = 'FULLY_USED' if new_remaining == Decimal('0') else 'ACTIVE'

        AdvancePayment.objects.filter(pk=advance.pk).update(
            amount_used=new_used, remaining=new_remaining, status=new_status
        )
        advance.refresh_from_db()

        AuditLog.log(request.user, 'UPDATE', advance, {
            'action': 'ADVANCE_ADJUST',
            'advance_number': advance.advance_number,
            'amount_adjusted': str(amount),
            'amount_used': str(new_used),
            'remaining': str(new_remaining),
            'status': new_status,
        })

        return Response({
            'message': 'Advance adjusted successfully',
            'amount_adjusted': float(amount),
            'advance': AdvancePaymentSerializer(advance).data,
        })

    def destroy(self, request, *args, **kwargs):
        return Response({'error': 'Advance payments cannot be deleted'}, status=status.HTTP_403_FORBIDDEN)


# ═════════════════════════════════════════════════════════════════════════════
# Profit & Loss Reports (INR)
# ═════════════════════════════════════════════════════════════════════════════

def _to_inr(amount, currency, conversion_rate):
    """Convert amount to INR using stored rate."""
    if currency == 'INR' or not conversion_rate:
        return amount
    return amount * conversion_rate


class ProfitLossReportView(APIView):
    """
    P&L per requisition. All calculations in INR.
    Optional: ?requisition=uuid
    """
    permission_classes = [FinanceModulePermission]

    def get(self, request):
        req_id = request.query_params.get('requisition')
        fy = request.query_params.get('fy')

        requisitions = Requisition.objects.all()
        if req_id:
            requisitions = requisitions.filter(id=req_id)
        if fy:
            try:
                fy_start_year = int(fy.split('-')[0])
                fy_start = date_type(fy_start_year, 4, 1)
                fy_end = date_type(fy_start_year + 1, 3, 31)
                requisitions = requisitions.filter(
                    requisition_date__gte=fy_start,
                    requisition_date__lte=fy_end
                )
            except (ValueError, IndexError):
                pass

        results = []
        for req in requisitions:
            pos = PurchaseOrder.objects.filter(
                requisition=req
            ).exclude(status='CANCELLED')

            po_total_inr = sum(
                _to_inr(po.total_amount, po.currency, po.conversion_rate)
                for po in pos
            )

            transport_po = TransportEntry.objects.filter(
                purchase_order__requisition=req
            ).exclude(status='CANCELLED').aggregate(
                total=Sum('total_cost')
            )['total'] or Decimal('0')

            transport_pi = TransportEntry.objects.filter(
                proforma_invoice__requisition=req
            ).exclude(status='CANCELLED').aggregate(
                total=Sum('total_cost')
            )['total'] or Decimal('0')

            transport_total = transport_po + transport_pi
            total_cost = po_total_inr + transport_total

            pis = ProformaInvoice.objects.filter(
                requisition=req
            ).exclude(status='CANCELLED')

            pi_total_inr = sum(
                _to_inr(pi.grand_total, pi.currency, pi.conversion_rate)
                for pi in pis
            )

            profit_loss = pi_total_inr - total_cost
            margin = (profit_loss / pi_total_inr * 100) if pi_total_inr > 0 else Decimal('0')

            alert = None
            if profit_loss < 0:
                alert = 'LOSS'
            elif margin < 10:
                alert = 'LOW_MARGIN'

            results.append({
                'requisition_id': str(req.id),
                'requisition_number': req.requisition_number,
                'requisition_date': req.requisition_date.isoformat() if req.requisition_date else None,
                'purchase_cost_inr': float(po_total_inr),
                'transport_cost_inr': float(transport_total),
                'total_cost_inr': float(total_cost),
                'sales_revenue_inr': float(pi_total_inr),
                'profit_loss_inr': float(profit_loss),
                'margin_percentage': round(float(margin), 2),
                'alert': alert,
                'is_stock_sale': False,
            })

        stock_sale_pis = ProformaInvoice.objects.filter(
            requisition__isnull=True
        ).exclude(status='CANCELLED')
        if fy:
            try:
                fy_start_year = int(fy.split('-')[0])
                fy_start = date_type(fy_start_year, 4, 1)
                fy_end = date_type(fy_start_year + 1, 3, 31)
                stock_sale_pis = stock_sale_pis.filter(
                    pi_date__gte=fy_start, pi_date__lte=fy_end
                )
            except (ValueError, IndexError):
                pass

        if stock_sale_pis.exists():
            stock_revenue_inr = Decimal('0')
            stock_cost_inr = Decimal('0')
            for pi in stock_sale_pis:
                pi_rev = _to_inr(pi.grand_total, pi.currency, pi.conversion_rate)
                stock_revenue_inr += pi_rev
                for pii in pi.items.select_related('product').all():
                    last_purchase = PurchaseOrderItem.objects.filter(
                        product=pii.product, is_received=True,
                    ).exclude(po__status='CANCELLED').select_related('po').order_by('-po__po_date').first()
                    if last_purchase:
                        rate = last_purchase.po.conversion_rate or Decimal('1')
                        if last_purchase.po.currency == 'INR':
                            rate = Decimal('1')
                        stock_cost_inr += last_purchase.rate * pii.quantity * rate

            stock_pl = stock_revenue_inr - stock_cost_inr
            stock_margin = (stock_pl / stock_revenue_inr * 100) if stock_revenue_inr > 0 else Decimal('0')
            results.append({
                'requisition_id': None,
                'requisition_number': 'STOCK SALES',
                'requisition_date': None,
                'purchase_cost_inr': float(stock_cost_inr),
                'transport_cost_inr': 0,
                'total_cost_inr': float(stock_cost_inr),
                'sales_revenue_inr': float(stock_revenue_inr),
                'profit_loss_inr': float(stock_pl),
                'margin_percentage': round(float(stock_margin), 2),
                'alert': 'LOSS' if stock_pl < 0 else ('LOW_MARGIN' if stock_margin < 10 else None),
                'is_stock_sale': True,
            })

        total_cost_all = sum(r['total_cost_inr'] for r in results)
        total_revenue_all = sum(r['sales_revenue_inr'] for r in results)
        total_pl = total_revenue_all - total_cost_all

        return Response({
            'currency': 'INR',
            'summary': {
                'total_purchase_cost': sum(r['purchase_cost_inr'] for r in results),
                'total_transport_cost': sum(r['transport_cost_inr'] for r in results),
                'total_cost': total_cost_all,
                'total_revenue': total_revenue_all,
                'total_profit_loss': total_pl,
                'overall_margin': round((total_pl / total_revenue_all * 100), 2) if total_revenue_all > 0 else 0,
            },
            'requisitions': results,
        })


class ProfitLossItemReportView(APIView):
    """
    P&L per item for a specific requisition. All in INR.
    Required: ?requisition=uuid
    """
    permission_classes = [FinanceModulePermission]

    def get(self, request):
        req_id = request.query_params.get('requisition')
        if not req_id:
            return Response({'error': 'requisition param required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            req = Requisition.objects.get(id=req_id)
        except Requisition.DoesNotExist:
            return Response({'error': 'Requisition not found'}, status=status.HTTP_404_NOT_FOUND)

        po_items = PurchaseOrderItem.objects.filter(
            po__requisition=req
        ).exclude(po__status='CANCELLED').select_related('product', 'po')

        pi_items = ProformaInvoiceItem.objects.filter(
            proforma_invoice__requisition=req
        ).exclude(proforma_invoice__status='CANCELLED').select_related('product', 'proforma_invoice')

        transport_po = TransportEntry.objects.filter(
            purchase_order__requisition=req
        ).exclude(status='CANCELLED').aggregate(total=Sum('total_cost'))['total'] or Decimal('0')

        transport_pi = TransportEntry.objects.filter(
            proforma_invoice__requisition=req
        ).exclude(status='CANCELLED').aggregate(total=Sum('total_cost'))['total'] or Decimal('0')

        transport_total = transport_po + transport_pi

        po_items_total_inr = Decimal('0')
        product_data = {}

        for poi in po_items:
            rate = poi.po.conversion_rate or Decimal('1')
            if poi.po.currency == 'INR':
                rate = Decimal('1')
            item_inr = poi.amount * rate
            po_items_total_inr += item_inr

            pid = str(poi.product.id)
            if pid not in product_data:
                product_data[pid] = {
                    'product_id': pid,
                    'product_code': poi.product.item_code,
                    'product_name': poi.product.item_name,
                    'unit': poi.product.unit,
                    'purchase_qty': Decimal('0'),
                    'purchase_amount_inr': Decimal('0'),
                    'purchase_amount_original': Decimal('0'),
                    'purchase_currency': 'INR',
                    'purchase_conversion_rate': float(rate),
                    'selling_qty': Decimal('0'),
                    'selling_amount_inr': Decimal('0'),
                    'selling_amount_original': Decimal('0'),
                    'selling_currency': 'INR',
                    'selling_conversion_rate': 1,
                }
            product_data[pid]['purchase_qty'] += poi.quantity
            product_data[pid]['purchase_amount_inr'] += item_inr
            product_data[pid]['purchase_amount_original'] += poi.amount
            product_data[pid]['purchase_currency'] = poi.po.currency
            product_data[pid]['purchase_conversion_rate'] = float(rate)

        for pii in pi_items:
            rate = pii.proforma_invoice.conversion_rate or Decimal('1')
            if pii.proforma_invoice.currency == 'INR':
                rate = Decimal('1')
            item_inr = pii.amount * rate

            pid = str(pii.product.id)
            if pid not in product_data:
                product_data[pid] = {
                    'product_id': pid,
                    'product_code': pii.product.item_code,
                    'product_name': pii.product.item_name,
                    'unit': pii.product.unit,
                    'purchase_qty': Decimal('0'),
                    'purchase_amount_inr': Decimal('0'),
                    'purchase_amount_original': Decimal('0'),
                    'purchase_currency': 'INR',
                    'purchase_conversion_rate': 1,
                    'selling_qty': Decimal('0'),
                    'selling_amount_inr': Decimal('0'),
                    'selling_amount_original': Decimal('0'),
                    'selling_currency': 'INR',
                    'selling_conversion_rate': 1,
                }
            product_data[pid]['selling_qty'] += pii.quantity
            product_data[pid]['selling_amount_inr'] += item_inr
            product_data[pid]['selling_amount_original'] += pii.amount
            product_data[pid]['selling_currency'] = pii.proforma_invoice.currency
            product_data[pid]['selling_conversion_rate'] = float(rate)

        items_result = []
        for pid, data in product_data.items():
            value_pct = (data['purchase_amount_inr'] / po_items_total_inr) if po_items_total_inr > 0 else Decimal('0')
            allocated_transport = transport_total * value_pct
            total_cost = data['purchase_amount_inr'] + allocated_transport
            profit_loss = data['selling_amount_inr'] - total_cost
            margin = (profit_loss / data['selling_amount_inr'] * 100) if data['selling_amount_inr'] > 0 else Decimal('0')

            alert = None
            if profit_loss < 0:
                alert = 'LOSS'
            elif margin < 10:
                alert = 'LOW_MARGIN'

            items_result.append({
                'product_id': data['product_id'],
                'product_code': data['product_code'],
                'product_name': data['product_name'],
                'unit': data['unit'],
                'purchase_qty': float(data['purchase_qty']),
                'purchase_amount_inr': float(data['purchase_amount_inr']),
                'purchase_amount_original': float(data['purchase_amount_original']),
                'purchase_currency': data['purchase_currency'],
                'purchase_conversion_rate': data['purchase_conversion_rate'],
                'allocated_transport_inr': float(allocated_transport),
                'total_cost_inr': float(total_cost),
                'selling_qty': float(data['selling_qty']),
                'selling_amount_inr': float(data['selling_amount_inr']),
                'selling_amount_original': float(data['selling_amount_original']),
                'selling_currency': data['selling_currency'],
                'selling_conversion_rate': data['selling_conversion_rate'],
                'profit_loss_inr': float(profit_loss),
                'margin_percentage': round(float(margin), 2),
                'alert': alert,
            })

        return Response({
            'currency': 'INR',
            'requisition_number': req.requisition_number,
            'total_transport_cost': float(transport_total),
            'items': items_result,
        })


# ═════════════════════════════════════════════════════════════════════════════
# Real-time Profit Preview (during Sales/PI creation)
# ═════════════════════════════════════════════════════════════════════════════

class ProfitPreviewView(APIView):
    """
    Show expected profit while creating a PI.
    POST: { requisition: uuid, selling_price_inr: number, currency: "USD", conversion_rate: 84 }
    """
    permission_classes = [FinanceModulePermission]

    def post(self, request):
        req_id = request.data.get('requisition')
        selling_price = request.data.get('selling_price_inr')
        currency = request.data.get('currency', 'INR')
        conv_rate = request.data.get('conversion_rate')

        if not req_id or selling_price is None:
            return Response({'error': 'requisition and selling_price_inr required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            req = Requisition.objects.get(id=req_id)
        except Requisition.DoesNotExist:
            return Response({'error': 'Requisition not found'}, status=status.HTTP_404_NOT_FOUND)

        selling_inr = Decimal(str(selling_price))
        if currency != 'INR' and conv_rate:
            selling_inr = Decimal(str(selling_price)) * Decimal(str(conv_rate))

        pos = PurchaseOrder.objects.filter(requisition=req).exclude(status='CANCELLED')
        purchase_cost_inr = sum(
            _to_inr(po.total_amount, po.currency, po.conversion_rate) for po in pos
        )

        transport_cost = TransportEntry.objects.filter(
            Q(purchase_order__requisition=req) | Q(proforma_invoice__requisition=req)
        ).exclude(status='CANCELLED').aggregate(total=Sum('total_cost'))['total'] or Decimal('0')

        total_cost = purchase_cost_inr + transport_cost
        expected_profit = selling_inr - total_cost
        margin = (expected_profit / selling_inr * 100) if selling_inr > 0 else Decimal('0')

        alert = None
        if expected_profit < 0:
            alert = 'LOSS'
        elif margin < 10:
            alert = 'LOW_MARGIN'

        return Response({
            'currency': 'INR',
            'purchase_cost_inr': float(purchase_cost_inr),
            'transport_cost_inr': float(transport_cost),
            'total_cost_inr': float(total_cost),
            'selling_price_inr': float(selling_inr),
            'expected_profit_inr': float(expected_profit),
            'expected_margin_percentage': round(float(margin), 2),
            'alert': alert,
        })


# ═════════════════════════════════════════════════════════════════════════════
# Item Analytics
# ═════════════════════════════════════════════════════════════════════════════

class ItemAnalyticsView(APIView):
    """
    Per-item analytics: purchase count, sale count, purchased-not-sold, etc.
    """
    permission_classes = [FinanceModulePermission]

    def get(self, request):
        products = Product.objects.filter(is_active=True)

        items = []
        for p in products:
            po_count = PurchaseOrderItem.objects.filter(
                product=p, is_received=True
            ).exclude(po__status='CANCELLED').count()

            pi_count = ProformaInvoiceItem.objects.filter(
                product=p
            ).exclude(proforma_invoice__status='CANCELLED').count()

            po_qty = PurchaseOrderItem.objects.filter(
                product=p, is_received=True
            ).exclude(po__status='CANCELLED').aggregate(
                total=Sum('quantity')
            )['total'] or Decimal('0')

            pi_qty = ProformaInvoiceItem.objects.filter(
                product=p
            ).exclude(proforma_invoice__status='CANCELLED').aggregate(
                total=Sum('quantity')
            )['total'] or Decimal('0')

            items.append({
                'product_id': str(p.id),
                'item_code': p.item_code,
                'item_name': p.item_name,
                'unit': p.unit,
                'current_stock': float(p.current_stock),
                'total_times_purchased': po_count,
                'total_times_sold': pi_count,
                'total_qty_purchased': float(po_qty),
                'total_qty_sold': float(pi_qty),
                'purchased_not_sold': po_count > 0 and pi_count == 0,
                'sold_not_purchased': pi_count > 0 and po_count == 0,
                'last_purchase_date': p.last_purchase_date.isoformat() if p.last_purchase_date else None,
                'last_sale_date': p.last_sale_date.isoformat() if p.last_sale_date else None,
            })

        return Response({
            'total_items': len(items),
            'items': items,
        })


class ItemInsightsView(APIView):
    """
    Advanced item insights: most sold, least sold, most profitable, loss-making.
    """
    permission_classes = [FinanceModulePermission]

    def get(self, request):
        products = Product.objects.filter(is_active=True)

        product_stats = []
        for p in products:
            po_amount = PurchaseOrderItem.objects.filter(
                product=p, is_received=True
            ).exclude(po__status='CANCELLED').aggregate(total=Sum('amount'))['total'] or Decimal('0')

            pi_amount = ProformaInvoiceItem.objects.filter(
                product=p
            ).exclude(proforma_invoice__status='CANCELLED').aggregate(total=Sum('amount'))['total'] or Decimal('0')

            pi_qty = ProformaInvoiceItem.objects.filter(
                product=p
            ).exclude(proforma_invoice__status='CANCELLED').aggregate(total=Sum('quantity'))['total'] or Decimal('0')

            profit = pi_amount - po_amount

            product_stats.append({
                'product_id': str(p.id),
                'item_code': p.item_code,
                'item_name': p.item_name,
                'total_purchased_amount': float(po_amount),
                'total_sold_amount': float(pi_amount),
                'total_sold_qty': float(pi_qty),
                'profit_loss': float(profit),
                'last_purchase_date': p.last_purchase_date.isoformat() if p.last_purchase_date else None,
                'last_sale_date': p.last_sale_date.isoformat() if p.last_sale_date else None,
            })

        sold_items = [i for i in product_stats if i['total_sold_qty'] > 0]
        most_sold = sorted(sold_items, key=lambda x: x['total_sold_qty'], reverse=True)[:10]
        least_sold = sorted(sold_items, key=lambda x: x['total_sold_qty'])[:10]

        profitable = sorted(
            [i for i in product_stats if i['profit_loss'] > 0],
            key=lambda x: x['profit_loss'], reverse=True
        )[:10]

        loss_making = sorted(
            [i for i in product_stats if i['profit_loss'] < 0],
            key=lambda x: x['profit_loss']
        )[:10]

        return Response({
            'most_sold': most_sold,
            'least_sold': least_sold,
            'most_profitable': profitable,
            'loss_making': loss_making,
        })


class InventoryAgingView(APIView):
    """
    Inventory aging: slow-moving and dead stock identification.
    """
    permission_classes = [FinanceModulePermission]

    def get(self, request):
        threshold_days = int(request.query_params.get('threshold_days', 90))
        today = date_type.today()
        cutoff = today - timedelta(days=threshold_days)

        products = Product.objects.filter(is_active=True, current_stock__gt=0)

        slow_moving = []
        dead_stock = []

        for p in products:
            days_unsold = None
            if p.last_sale_date:
                days_unsold = (today - p.last_sale_date).days
            elif p.last_purchase_date:
                days_unsold = (today - p.last_purchase_date).days

            item = {
                'product_id': str(p.id),
                'item_code': p.item_code,
                'item_name': p.item_name,
                'current_stock': float(p.current_stock),
                'unit': p.unit,
                'last_purchase_date': p.last_purchase_date.isoformat() if p.last_purchase_date else None,
                'last_sale_date': p.last_sale_date.isoformat() if p.last_sale_date else None,
                'days_unsold': days_unsold,
            }

            if days_unsold and days_unsold > threshold_days * 2:
                dead_stock.append(item)
            elif days_unsold and days_unsold > threshold_days:
                slow_moving.append(item)
            elif not p.last_sale_date and not p.last_purchase_date:
                dead_stock.append(item)

        return Response({
            'threshold_days': threshold_days,
            'slow_moving': {
                'count': len(slow_moving),
                'items': slow_moving,
            },
            'dead_stock': {
                'count': len(dead_stock),
                'items': dead_stock,
            },
        })


# ═════════════════════════════════════════════════════════════════════════════
# Payment Tracking & Due Dates
# ═════════════════════════════════════════════════════════════════════════════

class DueDateTrackingView(APIView):
    """
    Upcoming and overdue payments (both vendor and client).
    """
    permission_classes = [FinanceModulePermission]

    def get(self, request):
        today = date_type.today()
        upcoming_days = int(request.query_params.get('upcoming_days', 7))
        upcoming_cutoff = today + timedelta(days=upcoming_days)

        # Vendor payments (PO) — upcoming due
        upcoming_vendor = PurchaseOrder.objects.filter(
            payment_due_date__gte=today,
            payment_due_date__lte=upcoming_cutoff,
            total_amount__gt=F('amount_paid'),
        ).exclude(status='CANCELLED').select_related('vendor')

        # Vendor overdue
        overdue_vendor = PurchaseOrder.objects.filter(
            payment_due_date__lt=today,
            total_amount__gt=F('amount_paid'),
        ).exclude(status='CANCELLED').select_related('vendor')

        # Client payments (PI) — upcoming
        upcoming_client = ProformaInvoice.objects.filter(
            payment_due_date__gte=today,
            payment_due_date__lte=upcoming_cutoff,
            grand_total__gt=F('amount_received'),
        ).exclude(status='CANCELLED').select_related('requisition')

        # Client overdue
        overdue_client = ProformaInvoice.objects.filter(
            payment_due_date__lt=today,
            grand_total__gt=F('amount_received'),
        ).exclude(status='CANCELLED').select_related('requisition')

        return Response({
            'vendor_payments': {
                'upcoming': [{
                    'po_number': po.po_number,
                    'vendor_name': po.vendor.vendor_name,
                    'balance': float(max(po.total_amount - po.amount_paid, Decimal('0'))),
                    'due_date': po.payment_due_date.isoformat(),
                    'days_until_due': (po.payment_due_date - today).days,
                } for po in upcoming_vendor],
                'overdue': [{
                    'po_number': po.po_number,
                    'vendor_name': po.vendor.vendor_name,
                    'balance': float(max(po.total_amount - po.amount_paid, Decimal('0'))),
                    'due_date': po.payment_due_date.isoformat(),
                    'days_overdue': (today - po.payment_due_date).days,
                } for po in overdue_vendor],
            },
            'client_payments': {
                'upcoming': [{
                    'pi_number': pi.pi_number,
                    'requisition_number': pi.requisition.requisition_number if pi.requisition else 'STOCK SALE',
                    'balance': float(max(pi.grand_total - pi.amount_received, Decimal('0'))),
                    'due_date': pi.payment_due_date.isoformat(),
                    'days_until_due': (pi.payment_due_date - today).days,
                } for pi in upcoming_client],
                'overdue': [{
                    'pi_number': pi.pi_number,
                    'requisition_number': pi.requisition.requisition_number if pi.requisition else 'STOCK SALE',
                    'balance': float(max(pi.grand_total - pi.amount_received, Decimal('0'))),
                    'due_date': pi.payment_due_date.isoformat(),
                    'days_overdue': (today - pi.payment_due_date).days,
                } for pi in overdue_client],
            },
        })


# ═════════════════════════════════════════════════════════════════════════════
# Auto Reconciliation
# ═════════════════════════════════════════════════════════════════════════════

class ReconciliationView(APIView):
    """
    Detect mismatches: overpayment, underpayment, duplicate, unmatched entries.
    """
    permission_classes = [FinanceModulePermission]

    def get(self, request):
        overpaid_pos = []
        underpaid_completed_pos = []

        for po in PurchaseOrder.objects.exclude(status='CANCELLED'):
            balance = po.total_amount - po.amount_paid
            if balance < 0:
                overpaid_pos.append({
                    'po_number': po.po_number,
                    'total_amount': float(po.total_amount),
                    'amount_paid': float(po.amount_paid),
                    'overpayment': float(abs(balance)),
                })
            elif po.status == 'COMPLETED' and balance > 0:
                underpaid_completed_pos.append({
                    'po_number': po.po_number,
                    'total_amount': float(po.total_amount),
                    'amount_paid': float(po.amount_paid),
                    'remaining': float(balance),
                })

        overpaid_pis = []
        underpaid_accepted_pis = []

        for pi in ProformaInvoice.objects.exclude(status='CANCELLED'):
            balance = pi.grand_total - pi.amount_received
            if balance < 0:
                overpaid_pis.append({
                    'pi_number': pi.pi_number,
                    'grand_total': float(pi.grand_total),
                    'amount_received': float(pi.amount_received),
                    'overpayment': float(abs(balance)),
                })
            elif pi.status == 'ACCEPTED' and balance > 0:
                underpaid_accepted_pis.append({
                    'pi_number': pi.pi_number,
                    'grand_total': float(pi.grand_total),
                    'amount_received': float(pi.amount_received),
                    'remaining': float(balance),
                })

        # Duplicate payment detection (same amount, same day, same PO/PI)
        from django.db.models.functions import TruncDate
        duplicate_purchase = PurchasePayment.objects.values(
            'purchase_order', 'amount', 'payment_date'
        ).annotate(count=Count('id')).filter(count__gt=1)

        duplicate_pi = PIPayment.objects.values(
            'proforma_invoice', 'amount', 'payment_date'
        ).annotate(count=Count('id')).filter(count__gt=1)

        # PO without transport
        po_without_transport = PurchaseOrder.objects.exclude(
            status='CANCELLED'
        ).filter(transport_entries__isnull=True).values_list('po_number', flat=True)[:20]

        # PI without transport
        pi_without_transport = ProformaInvoice.objects.exclude(
            status='CANCELLED'
        ).filter(transport_entries__isnull=True).values_list('pi_number', flat=True)[:20]

        return Response({
            'overpayments': {
                'purchase_orders': overpaid_pos,
                'proforma_invoices': overpaid_pis,
            },
            'underpayments': {
                'completed_pos_with_balance': underpaid_completed_pos,
                'accepted_pis_with_balance': underpaid_accepted_pis,
            },
            'potential_duplicates': {
                'purchase_payments': list(duplicate_purchase),
                'pi_payments': list(duplicate_pi),
            },
            'missing_transport': {
                'pos_without_transport': list(po_without_transport),
                'pis_without_transport': list(pi_without_transport),
            },
        })


# ═════════════════════════════════════════════════════════════════════════════
# Finance Validation
# ═════════════════════════════════════════════════════════════════════════════

class FinanceValidationView(APIView):
    """
    Identify anomalies across modules.
    """
    permission_classes = [FinanceModulePermission]

    def get(self, request):
        # Purchased but unpaid
        purchased_unpaid = PurchaseOrder.objects.filter(
            items__is_received=True,
            amount_paid=0,
        ).exclude(status='CANCELLED').distinct().values_list('po_number', flat=True)[:20]

        # Paid but not purchased (paid > 0, no items received)
        paid_not_purchased = PurchaseOrder.objects.exclude(
            status='CANCELLED'
        ).filter(amount_paid__gt=0).exclude(
            items__is_received=True
        ).values_list('po_number', flat=True)[:20]

        # Sold (PI sent/accepted) but no payment received
        sold_unpaid = ProformaInvoice.objects.filter(
            status__in=['SENT', 'ACCEPTED'],
            amount_received=0,
            grand_total__gt=0,
        ).values_list('pi_number', flat=True)[:20]

        # Payment received but PI still in DRAFT
        paid_not_sold = ProformaInvoice.objects.filter(
            status='DRAFT',
            amount_received__gt=0,
        ).values_list('pi_number', flat=True)[:20]

        # PO without transport cost
        po_no_transport = PurchaseOrder.objects.exclude(
            status='CANCELLED'
        ).filter(transport_entries__isnull=True).count()

        # PI without transport cost
        pi_no_transport = ProformaInvoice.objects.exclude(
            status='CANCELLED'
        ).filter(transport_entries__isnull=True).count()

        # Advance not adjusted
        unadjusted_advances = AdvancePayment.objects.filter(
            status='ACTIVE', remaining__gt=0
        ).count()

        return Response({
            'purchased_but_unpaid': list(purchased_unpaid),
            'paid_but_not_purchased': list(paid_not_purchased),
            'sold_but_unpaid': list(sold_unpaid),
            'paid_but_not_sold': list(paid_not_sold),
            'po_without_transport': po_no_transport,
            'pi_without_transport': pi_no_transport,
            'unadjusted_advances': unadjusted_advances,
        })


# ═════════════════════════════════════════════════════════════════════════════
# Finance Dashboard (Comprehensive)
# ═════════════════════════════════════════════════════════════════════════════

class FinanceDashboardView(APIView):
    permission_classes = [FinanceModulePermission]

    def get(self, request):
        today = date_type.today()

        # ── Outgoing (PO → Vendor) ──────────────────────────────────────────
        pos = PurchaseOrder.objects.exclude(status='CANCELLED')
        total_po_value = pos.aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
        total_paid_to_vendors = pos.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0')
        outstanding_to_vendors = max(total_po_value - total_paid_to_vendors, Decimal('0'))
        pending_po_count = pos.filter(total_amount__gt=F('amount_paid')).count()

        # ── Incoming (PI → Client) ──────────────────────────────────────────
        pis = ProformaInvoice.objects.exclude(status='CANCELLED')
        total_pi_value = pis.aggregate(total=Sum('grand_total'))['total'] or Decimal('0')
        total_received_from_clients = pis.aggregate(total=Sum('amount_received'))['total'] or Decimal('0')
        outstanding_from_clients = max(total_pi_value - total_received_from_clients, Decimal('0'))
        pending_pi_count = pis.filter(grand_total__gt=F('amount_received')).count()

        # ── Transport costs ──────────────────────────────────────────────────
        total_transport = TransportEntry.objects.exclude(
            status='CANCELLED'
        ).aggregate(total=Sum('total_cost'))['total'] or Decimal('0')

        # ── P&L Summary ──────────────────────────────────────────────────────
        total_revenue_inr = sum(
            _to_inr(pi.grand_total, pi.currency, pi.conversion_rate)
            for pi in pis
        )
        total_cost_inr = sum(
            _to_inr(po.total_amount, po.currency, po.conversion_rate)
            for po in pos
        ) + total_transport
        total_profit = total_revenue_inr - total_cost_inr

        # ── Cash flow ────────────────────────────────────────────────────────
        total_inflow = total_received_from_clients
        total_outflow = total_paid_to_vendors + total_transport

        # ── Due dates ────────────────────────────────────────────────────────
        overdue_vendor_count = pos.filter(
            payment_due_date__lt=today, total_amount__gt=F('amount_paid')
        ).count()
        overdue_client_count = pis.filter(
            payment_due_date__lt=today, grand_total__gt=F('amount_received')
        ).count()

        # ── Advance payments ─────────────────────────────────────────────────
        active_advances = AdvancePayment.objects.filter(status='ACTIVE')
        total_advance_remaining = active_advances.aggregate(
            total=Sum('remaining')
        )['total'] or Decimal('0')

        # ── Recent activity ──────────────────────────────────────────────────
        recent_outgoing = PurchasePayment.objects.select_related(
            'purchase_order__vendor', 'recorded_by'
        ).order_by('-created_at')[:5]
        recent_incoming = PIPayment.objects.select_related(
            'proforma_invoice', 'recorded_by'
        ).order_by('-created_at')[:5]

        # ── Purchase items ───────────────────────────────────────────────────
        total_po_items = PurchaseOrderItem.objects.exclude(po__status='CANCELLED').count()
        purchased_items = PurchaseOrderItem.objects.filter(
            is_received=True
        ).exclude(po__status='CANCELLED').count()

        return Response({
            'outgoing': {
                'label': 'Payments to Vendors (PO)',
                'total_value': float(total_po_value),
                'total_paid': float(total_paid_to_vendors),
                'outstanding': float(outstanding_to_vendors),
                'pending_count': pending_po_count,
                'overdue_count': overdue_vendor_count,
            },
            'incoming': {
                'label': 'Payments from Clients (PI)',
                'total_value': float(total_pi_value),
                'total_received': float(total_received_from_clients),
                'outstanding': float(outstanding_from_clients),
                'pending_count': pending_pi_count,
                'overdue_count': overdue_client_count,
            },
            'transport': {
                'total_cost': float(total_transport),
            },
            'profit_loss': {
                'currency': 'INR',
                'total_revenue': float(total_revenue_inr),
                'total_cost': float(total_cost_inr),
                'total_profit': float(total_profit),
                'margin_percentage': round(
                    float(total_profit / total_revenue_inr * 100), 2
                ) if total_revenue_inr > 0 else 0,
            },
            'cash_flow': {
                'total_inflow': float(total_inflow),
                'total_outflow': float(total_outflow),
                'net_flow': float(total_inflow - total_outflow),
            },
            'advances': {
                'active_count': active_advances.count(),
                'total_remaining': float(total_advance_remaining),
            },
            'purchase_items': {
                'total_items': total_po_items,
                'purchased_items': purchased_items,
                'pending_items': total_po_items - purchased_items,
            },
            'recent_outgoing': PurchasePaymentSerializer(recent_outgoing, many=True).data,
            'recent_incoming': PIPaymentSerializer(recent_incoming, many=True).data,
        })
