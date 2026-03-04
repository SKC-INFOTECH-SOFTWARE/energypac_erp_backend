from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django_filters.rest_framework import DjangoFilterBackend
from django.http import FileResponse
from django.conf import settings
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes, inline_serializer
from rest_framework import serializers as drf_serializers
import os

from .models import ClientQuery, SalesQuotation, SalesQuotationItem
from .serializers import (
    ClientQuerySerializer,
    ClientQueryCreateSerializer,
    SalesQuotationSerializer,
    SalesQuotationCreateSerializer,
    SalesQuotationUpdateSerializer,
    SalesQuotationItemSerializer,
)


class ClientQueryViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Client Query CRUD operations
    Features:
    - Upload PDF files with client queries
    - Track query status
    - Link to quotations
    """
    queryset = ClientQuery.objects.all().select_related('created_by')
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'query_date', 'created_by']
    search_fields = ['query_number', 'client_name', 'contact_person', 'email', 'remarks']
    ordering_fields = ['query_date', 'created_at', 'query_number']
    ordering = ['-query_number']

    def get_serializer_class(self):
        if self.action == 'create':
            return ClientQueryCreateSerializer
        return ClientQuerySerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @extend_schema(
        responses={(200, 'application/pdf'): OpenApiTypes.BINARY},
        summary="Download PDF"
    )
    @action(detail=True, methods=['get'])
    def download_pdf(self, request, pk=None):
        """Download the uploaded PDF file"""
        query = self.get_object()
        if not query.pdf_file or not os.path.exists(os.path.join(settings.BASE_DIR, query.pdf_file)):
            return Response(
                {'error': 'PDF file not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        try:
            return FileResponse(
                open(os.path.join(settings.BASE_DIR, query.pdf_file), 'rb'),
                content_type='application/pdf',
                as_attachment=True,
                filename=f"{query.query_number}.pdf"
            )
        except Exception as e:
            return Response(
                {'error': f'Error downloading file: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        responses=SalesQuotationSerializer(many=True),
        summary="Get quotations for query"
    )
    @action(detail=True, methods=['get'])
    def quotations(self, request, pk=None):
        """Get all quotations for this query"""
        query = self.get_object()
        quotations = query.quotations.all()
        serializer = SalesQuotationSerializer(quotations, many=True)
        return Response({
            'query_number': query.query_number,
            'client_name': query.client_name,
            'total_quotations': quotations.count(),
            'quotations': serializer.data
        })

    @extend_schema(
        request=inline_serializer(
            name='ClientQueryStatusUpdate',
            fields={
                'status': drf_serializers.ChoiceField(
                    choices=ClientQuery._meta.get_field('status').choices
                )
            }
        ),
        responses=ClientQuerySerializer,
        summary="Update query status"
    )
    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        """Update query status"""
        query = self.get_object()
        new_status = request.data.get('status')
        if new_status not in dict(ClientQuery._meta.get_field('status').choices):
            return Response(
                {'error': 'Invalid status'},
                status=status.HTTP_400_BAD_REQUEST
            )
        query.status = new_status
        query.save()
        serializer = self.get_serializer(query)
        return Response(serializer.data)


class SalesQuotationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Sales Quotation CRUD operations

    Endpoints
    ---------
    Standard CRUD:
        GET    /api/quotations                  – list all quotations
        POST   /api/quotations                  – create new quotation
        GET    /api/quotations/{id}             – retrieve quotation
        PUT    /api/quotations/{id}             – full update  (all fields + items)
        PATCH  /api/quotations/{id}             – partial update

    Custom actions:
        POST   /api/quotations/{id}/recalculate    – recalculate totals
        POST   /api/quotations/{id}/update_gst     – update GST only
        POST   /api/quotations/{id}/update_status  – update status only
        GET    /api/quotations/{id}/items          – list items
        GET    /api/quotations/{id}/summary        – full formatted summary
        GET    /api/quotations/by_status           – filter by status

    PUT / PATCH body for full update
    ---------------------------------
    Any combination of the following fields:
    {
        "quotation_date":  "2026-03-01",
        "validity_date":   "2026-03-31",
        "payment_terms":   "30 days net",
        "delivery_terms":  "Ex-works",
        "remarks":         "Revised per call",
        "cgst_percentage": 9,
        "sgst_percentage": 9,
        "igst_percentage": 0,
        "status":          "SENT",
        "items": [
            {
                "id":       "existing-item-uuid",   // omit to create new
                "quantity": 5,
                "rate":     1200,
                "remarks":  "updated"
            },
            {
                "item_code": "NEW001",              // no id → new item
                "item_name": "New Widget",
                "unit":      "PCS",
                "quantity":  2,
                "rate":      500
            }
            // items NOT listed here are deleted
        ]
    }
    """
    queryset = SalesQuotation.objects.all().select_related(
        'client_query', 'created_by'
    ).prefetch_related('items__product')
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields   = ['client_query', 'status', 'quotation_date']
    search_fields      = [
        'quotation_number', 'client_query__client_name',
        'client_query__query_number'
    ]
    ordering_fields    = ['quotation_date', 'created_at', 'total_amount']
    ordering           = ['-quotation_number']

    def get_serializer_class(self):
        if self.action == 'create':
            return SalesQuotationCreateSerializer
        if self.action in ('update', 'partial_update'):
            return SalesQuotationUpdateSerializer
        return SalesQuotationSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    # ── custom actions ────────────────────────────────────────────────────────

    @extend_schema(
        request=None,
        responses=SalesQuotationSerializer,
        summary="Recalculate totals"
    )
    @action(detail=True, methods=['post'])
    def recalculate(self, request, pk=None):
        """Recalculate totals for quotation"""
        quotation = self.get_object()
        quotation.calculate_totals()
        serializer = SalesQuotationSerializer(quotation)
        return Response(serializer.data)

    @extend_schema(
        request=inline_serializer(
            name='SalesQuotationGSTUpdate',
            fields={
                'cgst_percentage': drf_serializers.DecimalField(max_digits=5, decimal_places=2, required=False),
                'sgst_percentage': drf_serializers.DecimalField(max_digits=5, decimal_places=2, required=False),
                'igst_percentage': drf_serializers.DecimalField(max_digits=5, decimal_places=2, required=False),
            }
        ),
        responses=SalesQuotationSerializer,
        summary="Update GST percentages only"
    )
    @action(detail=True, methods=['post'])
    def update_gst(self, request, pk=None):
        """Update GST percentages and recalculate (convenience shortcut)"""
        quotation = self.get_object()
        cgst = request.data.get('cgst_percentage')
        sgst = request.data.get('sgst_percentage')
        igst = request.data.get('igst_percentage')
        if cgst is not None:
            quotation.cgst_percentage = cgst
        if sgst is not None:
            quotation.sgst_percentage = sgst
        if igst is not None:
            quotation.igst_percentage = igst
        quotation.save()
        quotation.calculate_totals()
        serializer = SalesQuotationSerializer(quotation)
        return Response(serializer.data)

    @extend_schema(
        request=inline_serializer(
            name='SalesQuotationStatusUpdate',
            fields={
                'status': drf_serializers.ChoiceField(
                    choices=SalesQuotation._meta.get_field('status').choices
                )
            }
        ),
        responses=SalesQuotationSerializer,
        summary="Update quotation status only"
    )
    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        """Update quotation status (convenience shortcut)"""
        quotation = self.get_object()
        new_status = request.data.get('status')
        if new_status not in dict(SalesQuotation._meta.get_field('status').choices):
            return Response(
                {'error': 'Invalid status'},
                status=status.HTTP_400_BAD_REQUEST
            )
        quotation.status = new_status
        quotation.save()
        # Mirror onto client query when accepted
        if new_status == 'ACCEPTED':
            quotation.client_query.status = 'CONVERTED'
            quotation.client_query.save()
        serializer = SalesQuotationSerializer(quotation)
        return Response(serializer.data)

    @extend_schema(
        responses=SalesQuotationItemSerializer(many=True),
        summary="Get quotation items"
    )
    @action(detail=True, methods=['get'])
    def items(self, request, pk=None):
        """Get all items in quotation"""
        quotation = self.get_object()
        items = quotation.items.all()
        serializer = SalesQuotationItemSerializer(items, many=True)
        return Response({
            'quotation_number': quotation.quotation_number,
            'total_items': items.count(),
            'items': serializer.data
        })

    @extend_schema(
        parameters=[
            OpenApiParameter(name='status', description='Filter by status', required=True, type=OpenApiTypes.STR)
        ],
        responses=SalesQuotationSerializer(many=True),
        summary="Get quotations by status"
    )
    @action(detail=False, methods=['get'])
    def by_status(self, request):
        """Get quotations by status"""
        status_param = request.query_params.get('status')
        if not status_param:
            return Response(
                {'error': 'status parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        quotations = self.queryset.filter(status=status_param)
        serializer = SalesQuotationSerializer(quotations, many=True)
        return Response({
            'status': status_param,
            'count': quotations.count(),
            'quotations': serializer.data
        })

    @extend_schema(
        responses=inline_serializer(
            name='SalesQuotationSummary',
            fields={
                'quotation_number': drf_serializers.CharField(),
                'client_name': drf_serializers.CharField(),
                'total_amount': drf_serializers.FloatField(),
                'status': drf_serializers.CharField(),
            }
        ),
        summary="Get quotation summary with tax breakdown"
    )
    @action(detail=True, methods=['get'])
    def summary(self, request, pk=None):
        """Get quotation summary with tax breakdown"""
        quotation = self.get_object()
        items_summary = []
        for item in quotation.items.all():
            items_summary.append({
                'item_name':   item.item_name,
                'item_code':   item.item_code,
                'hsn_code':    item.hsn_code,
                'quantity':    float(item.quantity),
                'unit':        item.unit,
                'rate':        float(item.rate),
                'amount':      float(item.amount),
                'from_stock':  item.product is not None
            })
        return Response({
            'quotation_number': quotation.quotation_number,
            'client_name':      quotation.client_query.client_name,
            'contact_person':   quotation.client_query.contact_person,
            'phone':            quotation.client_query.phone,
            'email':            quotation.client_query.email,
            'address':          quotation.client_query.address,
            'quotation_date':   quotation.quotation_date,
            'validity_date':    quotation.validity_date,
            'items':            items_summary,
            'total_items':      len(items_summary),
            'subtotal':         float(quotation.subtotal),
            'taxes': {
                'cgst': {
                    'percentage': float(quotation.cgst_percentage),
                    'amount':     float(quotation.cgst_amount)
                },
                'sgst': {
                    'percentage': float(quotation.sgst_percentage),
                    'amount':     float(quotation.sgst_amount)
                },
                'igst': {
                    'percentage': float(quotation.igst_percentage),
                    'amount':     float(quotation.igst_amount)
                },
                'total_tax': float(
                    quotation.cgst_amount +
                    quotation.sgst_amount +
                    quotation.igst_amount
                )
            },
            'total_amount':   float(quotation.total_amount),
            'status':         quotation.status,
            'payment_terms':  quotation.payment_terms,
            'delivery_terms': quotation.delivery_terms,
            'remarks':        quotation.remarks
        })


class SalesQuotationItemViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing individual quotation items.
    Allows adding / updating / removing items after quotation creation.
    """
    queryset = SalesQuotationItem.objects.all().select_related('quotation', 'product')
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['quotation', 'product']
    search_fields    = ['item_name', 'item_code']

    def get_serializer_class(self):
        return SalesQuotationItemSerializer

    def perform_create(self, serializer):
        item = serializer.save()
        item.quotation.calculate_totals()

    def perform_update(self, serializer):
        item = serializer.save()
        item.quotation.calculate_totals()

    def perform_destroy(self, instance):
        quotation = instance.quotation
        instance.delete()
        quotation.calculate_totals()
