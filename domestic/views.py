from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.http import HttpResponse
from django.db import transaction
from django.db.models import Sum, Count
from django_filters.rest_framework import DjangoFilterBackend
from decimal import Decimal
from datetime import date as date_type, datetime

from core.permissions import SalesModulePermission
from core.password_confirm import check_password_confirmation
from audit_logs.models import AuditLog
from sales.models import ProformaInvoice

from .models import TaxInvoice, TaxInvoicePayment
from .serializers import (
    TaxInvoiceSerializer, TaxInvoiceWriteSerializer, TaxInvoicePaymentSerializer,
)
from .excel_service import build_tax_invoice_xlsx


# Company defaults (editable on the form)
COMPANY = {
    'company_name': 'ENERGYPAC ENGINEERING LIMITED',
    'company_address': "KB-22 'BHAKTA TOWER', 4TH FL, SECTOR-III, SALT LAKE, KOLKATA - 700 106.",
    'company_gstin': '19AABCE4975G1ZE',
    'company_pan': 'AABCE4975G',
    'company_iec': '0205015794',
    'copy_label': 'ORIGINAL FOR RECIPIENT',
    'bank_name': 'STANDARD CHARTERED BANK',
    'bank_account': '33105910823',
    'bank_ifsc': 'SCBL0036008',
    'state': 'WEST BENGAL',
    'state_code': '19',
}


class TaxInvoiceViewSet(viewsets.ModelViewSet):
    permission_classes = [SalesModulePermission]
    queryset = TaxInvoice.objects.all().select_related(
        'proforma_invoice', 'created_by'
    ).prefetch_related('items')
    serializer_class = TaxInvoiceSerializer

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['proforma_invoice', 'status', 'kind']
    search_fields = ['ti_number', 'invoice_no', 'proforma_invoice__pi_number', 'bill_to_name']
    ordering = ['-ti_number']

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return TaxInvoiceWriteSerializer
        return TaxInvoiceSerializer

    def perform_create(self, serializer):
        ti = serializer.save(created_by=self.request.user)
        AuditLog.log(self.request.user, 'CREATE', ti, {
            'ti_number': ti.ti_number,
            'kind': ti.get_kind_display(),
            'proforma_invoice': ti.proforma_invoice.pi_number if ti.proforma_invoice else 'Standalone',
            'total_amount_after_tax': str(ti.total_amount_after_tax),
        })

    def perform_update(self, serializer):
        ti = serializer.save()
        AuditLog.log(self.request.user, 'UPDATE', ti, {'ti_number': ti.ti_number})

    @action(detail=False, methods=['get'])
    def prefill(self, request):
        """
        GET /api/tax-invoices/prefill?proforma_invoice=<uuid>&kind=PRODUCT|SERVICE
        Prefills header + items from the DOMESTIC PI; everything stays editable.
        """
        pi_id = request.query_params.get('proforma_invoice')
        kind = request.query_params.get('kind', 'PRODUCT')
        if not pi_id:
            return Response({'error': 'proforma_invoice param required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            pi = ProformaInvoice.objects.prefetch_related('items__product').get(id=pi_id)
        except ProformaInvoice.DoesNotExist:
            return Response({'error': 'Proforma Invoice not found'}, status=status.HTTP_404_NOT_FOUND)
        if pi.trade_type != 'DOMESTIC':
            return Response({'error': 'PI is not DOMESTIC'}, status=status.HTTP_400_BAD_REQUEST)

        items = []
        for it in pi.items.all():
            name = it.product.item_name if it.product else ''
            hs = it.hsn_code or (it.product.hsn_code if it.product else '')
            items.append({
                'pi_item': str(it.id),
                'description': name,
                'hs_sac_code': hs,
                'quantity': float(it.quantity),
                'unit': (it.product.unit if it.product else 'No.'),
                'rate': float(it.unit_price),
                'amount': float(it.amount),
                'taxable_value': float(it.amount),
                'sgst_rate': 9, 'sgst_amount': 0,
                'cgst_rate': 9, 'cgst_amount': 0,
                'igst_rate': 0, 'igst_amount': 0,
                'total_amount': 0,
            })

        data = {
            'proforma_invoice': str(pi.id),
            'kind': kind if kind in ('PRODUCT', 'SERVICE') else 'PRODUCT',
            **COMPANY,
            'invoice_no': '', 'invoice_date': None,
            'challan_no': '', 'challan_date': None,
            'vendor_code': '', 'vehicle_no': '', 'mode_of_transport': 'BY ROAD',
            'place_of_supply': '', 'buyers_order_no': '', 'buyers_order_date': None,
            'work_order_no': '',
            'bill_to_name': pi.consignee or '', 'bill_to_address': '', 'bill_to_gstin': pi.gst_number or '',
            'bill_to_state': '',
            'ship_to_name': '', 'ship_to_address': '', 'ship_to_project': '', 'ship_to_state': '',
            'gst_on_reverse_charge': 'No',
            'terms_of_payment': [],
            'items': items,
        }
        return Response(data)

    @action(detail=False, methods=['get'])
    def blank(self, request):
        """
        GET /api/tax-invoices/blank?kind=SERVICE|PRODUCT
        Standalone invoice (no PI) — company/bank defaults, empty items.
        Used for Service Tax Invoices which are not tied to a Proforma Invoice.
        """
        kind = request.query_params.get('kind', 'SERVICE')
        kind = kind if kind in ('PRODUCT', 'SERVICE') else 'SERVICE'
        return Response({
            'proforma_invoice': None,
            'kind': kind,
            **COMPANY,
            'invoice_no': '', 'invoice_date': None, 'challan_no': '', 'challan_date': None,
            'vendor_code': '', 'vehicle_no': '',
            'mode_of_transport': 'BY ROAD' if kind == 'PRODUCT' else '',
            'place_of_supply': '', 'buyers_order_no': '', 'buyers_order_date': None, 'work_order_no': '',
            'bill_to_name': '', 'bill_to_address': '', 'bill_to_gstin': '', 'bill_to_state': '',
            'ship_to_name': '', 'ship_to_address': '', 'ship_to_project': '', 'ship_to_state': '',
            'gst_on_reverse_charge': 'No', 'terms_of_payment': [], 'items': [],
        })

    @action(detail=True, methods=['get'])
    def excel(self, request, pk=None):
        ti = self.get_object()
        stream = build_tax_invoice_xlsx(ti)
        resp = HttpResponse(
            stream.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        resp['Content-Disposition'] = f'attachment; filename="{ti.ti_number.replace("/", "_")}.xlsx"'
        return resp

    # ── Collection (Finance: Service Invoice Payments) ───────────────────────
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def record_payment(self, request, pk=None):
        password_error = check_password_confirmation(request)
        if password_error:
            return password_error

        ti = self.get_object()
        if ti.status == 'CANCELLED':
            return Response({'error': 'Cannot record payment on a cancelled invoice'}, status=status.HTTP_400_BAD_REQUEST)
        if ti.status == 'PAID':
            return Response({'error': 'Invoice is already fully paid'}, status=status.HTTP_400_BAD_REQUEST)

        raw_amount = request.data.get('amount')
        if raw_amount is None:
            return Response({'error': 'amount is required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            amount = Decimal(str(raw_amount))
        except Exception:
            return Response({'error': 'Invalid amount'}, status=status.HTTP_400_BAD_REQUEST)
        if amount <= Decimal('0'):
            return Response({'error': 'amount must be greater than 0'}, status=status.HTTP_400_BAD_REQUEST)

        outstanding = ti.total_amount_after_tax - ti.amount_paid
        if amount > outstanding:
            return Response({
                'error': 'Payment exceeds outstanding balance',
                'outstanding_balance': float(outstanding),
            }, status=status.HTTP_400_BAD_REQUEST)

        raw_date = request.data.get('payment_date')
        payment_date_value = date_type.today()
        if raw_date:
            try:
                payment_date_value = datetime.strptime(raw_date, '%Y-%m-%d').date()
            except ValueError:
                return Response({'error': 'Invalid payment_date — use YYYY-MM-DD'}, status=status.HTTP_400_BAD_REQUEST)

        ti.amount_paid = ti.amount_paid + amount
        ti.recalc_balance()
        ti.save()

        last = ti.payments.order_by('-payment_number').first()
        payment_number = (last.payment_number + 1) if last else 1
        payment = TaxInvoicePayment.objects.create(
            tax_invoice=ti,
            payment_number=payment_number,
            amount=amount,
            payment_date=payment_date_value,
            payment_mode=request.data.get('payment_mode', 'NEFT'),
            reference_number=request.data.get('reference_number', ''),
            remarks=request.data.get('remarks', ''),
            total_paid_after=ti.amount_paid,
            balance_after=ti.balance,
            recorded_by=request.user,
        )

        AuditLog.log(request.user, 'CREATE', payment, {
            'action': 'SERVICE_INVOICE_PAYMENT',
            'ti_number': ti.ti_number,
            'payment_number': payment_number,
            'amount': str(amount),
            'total_paid_after': str(ti.amount_paid),
            'balance_after': str(ti.balance),
        })

        return Response({
            'message': 'Payment recorded successfully',
            'payment_number': payment_number,
            'total_paid': float(ti.amount_paid),
            'balance': float(ti.balance),
            'status': ti.status,
            'invoice': TaxInvoiceSerializer(ti).data,
        })

    @action(detail=True, methods=['get'])
    def payment_history(self, request, pk=None):
        ti = self.get_object()
        payments = ti.payments.all().order_by('payment_number')
        return Response({
            'ti_number': ti.ti_number,
            'total_amount_after_tax': float(ti.total_amount_after_tax),
            'total_paid': float(ti.amount_paid),
            'balance': float(ti.balance),
            'status': ti.status,
            'total_payments': payments.count(),
            'payments': TaxInvoicePaymentSerializer(payments, many=True).data,
        })

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Billed / received / outstanding for the current filter (defaults to SERVICE)."""
        qs = self.filter_queryset(self.get_queryset()).exclude(status='CANCELLED')
        if 'kind' not in request.query_params:
            qs = qs.filter(kind='SERVICE')
        agg = qs.aggregate(
            count=Count('id'),
            total_billed=Sum('total_amount_after_tax'),
            total_received=Sum('amount_paid'),
            total_outstanding=Sum('balance'),
        )
        return Response({
            'count': agg['count'] or 0,
            'total_billed': float(agg['total_billed'] or 0),
            'total_received': float(agg['total_received'] or 0),
            'total_outstanding': float(agg['total_outstanding'] or 0),
        })
