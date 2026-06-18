from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.http import HttpResponse
from django_filters.rest_framework import DjangoFilterBackend

from core.permissions import SalesModulePermission
from audit_logs.models import AuditLog
from sales.models import ProformaInvoice

from .models import CommercialInvoice, PackingList
from .serializers import (
    CommercialInvoiceSerializer, CommercialInvoiceWriteSerializer,
    PackingListSerializer, PackingListWriteSerializer,
)
from .excel_service import build_commercial_invoice_xlsx, build_packing_list_xlsx


DEFAULT_DECLARATIONS = [
    "The goods are of Indian Origin",
    "Country of Origin was printed clearly on package/boxes/cartons of goods.",
    "The goods Description, Quality, Quantity, other particulars and price herein "
    "invoiced conformity to Proforma Invoice.",
]
DEFAULT_PACKING_SPEC = (
    "Export Standard Roadworthy Packing and Origin of the goods has been "
    "mentioned in the outside of the packages."
)


def _xlsx_response(stream, filename):
    resp = HttpResponse(
        stream.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp


class CommercialInvoiceViewSet(viewsets.ModelViewSet):
    permission_classes = [SalesModulePermission]
    queryset = CommercialInvoice.objects.all().select_related(
        'proforma_invoice', 'created_by'
    ).prefetch_related('items')
    serializer_class = CommercialInvoiceSerializer

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['proforma_invoice', 'status', 'currency']
    search_fields = ['ci_number', 'invoice_no', 'proforma_invoice__pi_number']
    ordering = ['-ci_number']

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return CommercialInvoiceWriteSerializer
        return CommercialInvoiceSerializer

    def perform_create(self, serializer):
        ci = serializer.save(created_by=self.request.user)
        AuditLog.log(self.request.user, 'CREATE', ci, {
            'ci_number': ci.ci_number,
            'proforma_invoice': ci.proforma_invoice.pi_number,
            'total_cpt_value': str(ci.total_cpt_value),
            'currency': ci.currency,
        })

    def perform_update(self, serializer):
        ci = serializer.save()
        AuditLog.log(self.request.user, 'UPDATE', ci, {'ci_number': ci.ci_number})

    @action(detail=False, methods=['get'])
    def prefill(self, request):
        """
        GET /api/commercial-invoices/prefill?proforma_invoice=<uuid>
        Returns header + item data mapped from the PI so the CI form can be
        pre-populated. Everything is editable on the frontend.
        """
        pi_id = request.query_params.get('proforma_invoice')
        if not pi_id:
            return Response({'error': 'proforma_invoice param required'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            pi = ProformaInvoice.objects.prefetch_related('items__product').get(id=pi_id)
        except ProformaInvoice.DoesNotExist:
            return Response({'error': 'Proforma Invoice not found'},
                            status=status.HTTP_404_NOT_FOUND)
        if pi.trade_type != 'INTERNATIONAL':
            return Response({'error': 'PI is not INTERNATIONAL'},
                            status=status.HTTP_400_BAD_REQUEST)

        items = []
        for it in pi.items.all():
            name = it.product.item_name if it.product else ''
            hs = it.hsn_code or (it.product.hsn_code if it.product else '')
            # Keep the HS code OUT of the description; it is rendered separately
            # (bold + centered) on the document.
            desc = name
            items.append({
                'pi_item': str(it.id),
                'marks_nos': '',
                'no_kind_pkgs': '',
                'description': desc,
                'hs_code': hs,
                'quantity': float(it.quantity),
                'unit': (it.product.unit if it.product else 'Nos.'),
                'unit_price': float(it.unit_price),
                'total_amount': float(it.amount),
            })

        data = {
            'proforma_invoice': str(pi.id),
            'invoice_no': '',
            'invoice_date': None,
            'exporters_ref': pi.exporter_reference or '',
            'gst_no': pi.gst_number or '',
            'buyers_order_no': '',
            'buyers_order_date': None,
            'exporter': pi.exporter_beneficiary or '',
            'consigned_to_order_of': pi.consignee or '',
            'importer_notify_party': pi.applicant_importer or '',
            'applicant': pi.applicant_importer or '',
            'terms_of_delivery': pi.terms_of_delivery or '',
            'terms_of_delivery_and_payment': pi.terms_of_payment or '',
            'place_of_supply': '',
            'vessel_flight_no': pi.pre_carriage_by or '',
            'port_of_loading': pi.port_of_loading or '',
            'port_of_discharge': pi.port_of_discharge or '',
            'place_of_delivery': '',
            'pre_carriage_by': pi.pre_carriage_by or '',
            'place_of_receipt': pi.place_of_receipt or '',
            'country_of_origin': pi.country_of_origin or '',
            'final_destination': pi.final_destination or '',
            'marks_from': '',
            'marks_to': '',
            'currency': pi.currency or 'USD',
            'total_freight': 0,
            'project_name': '',
            'declarations': [
                "The goods are of Indian Origin",
                "Country of Origin was printed clearly on package/boxes/cartons of goods.",
                "The goods Description, Quality, Quantity, other particulars and price herein "
                f"invoiced conformity to Proforma Invoice No: {pi.pi_number}.",
            ],
            'lut_no': '',
            'items': items,
        }
        return Response(data)

    @action(detail=True, methods=['get'])
    def excel(self, request, pk=None):
        ci = self.get_object()
        stream = build_commercial_invoice_xlsx(ci)
        return _xlsx_response(stream, f"{ci.ci_number.replace('/', '_')}.xlsx")


class PackingListViewSet(viewsets.ModelViewSet):
    permission_classes = [SalesModulePermission]
    queryset = PackingList.objects.all().select_related(
        'commercial_invoice', 'created_by'
    ).prefetch_related('items')
    serializer_class = PackingListSerializer

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['commercial_invoice', 'status']
    search_fields = ['pl_number', 'commercial_invoice__ci_number']
    ordering = ['-pl_number']

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return PackingListWriteSerializer
        return PackingListSerializer

    def perform_create(self, serializer):
        pl = serializer.save(created_by=self.request.user)
        AuditLog.log(self.request.user, 'CREATE', pl, {
            'pl_number': pl.pl_number,
            'commercial_invoice': pl.commercial_invoice.ci_number,
        })

    def perform_update(self, serializer):
        pl = serializer.save()
        AuditLog.log(self.request.user, 'UPDATE', pl, {'pl_number': pl.pl_number})

    @action(detail=False, methods=['get'])
    def prefill(self, request):
        """
        GET /api/packing-lists/prefill?commercial_invoice=<uuid>
        Mirrors the CI's descriptive columns; weights start blank for input.
        """
        ci_id = request.query_params.get('commercial_invoice')
        if not ci_id:
            return Response({'error': 'commercial_invoice param required'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            ci = CommercialInvoice.objects.prefetch_related('items').get(id=ci_id)
        except CommercialInvoice.DoesNotExist:
            return Response({'error': 'Commercial Invoice not found'},
                            status=status.HTTP_404_NOT_FOUND)

        items = [{
            'ci_item': str(it.id),
            'marks_nos': it.marks_nos,
            'no_kind_pkgs': it.no_kind_pkgs,
            'description': it.description,
            'hs_code': it.hs_code,
            'quantity': float(it.quantity),
            'unit': it.unit,
            'nett_weight': 0,
            'gross_weight': 0,
        } for it in ci.items.all()]

        return Response({
            'commercial_invoice': str(ci.id),
            'packing_specification': DEFAULT_PACKING_SPEC,
            'lut_no': ci.lut_no or '',
            'items': items,
        })

    @action(detail=True, methods=['get'])
    def excel(self, request, pk=None):
        pl = self.get_object()
        stream = build_packing_list_xlsx(pl)
        return _xlsx_response(stream, f"{pl.pl_number.replace('/', '_')}.xlsx")
