

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

from django.utils import timezone
from datetime import timedelta

from core.permissions import SalesModulePermission
from core.password_confirm import check_password_confirmation
from audit_logs.models import AuditLog
from .models import ClientQuery, SalesQuotation, SalesQuotationItem, ProformaInvoice
from .serializers import (
    ClientQuerySerializer,
    ClientQueryCreateSerializer,
    SalesQuotationSerializer,
    SalesQuotationCreateSerializer,
    SalesQuotationUpdateSerializer,
    SalesQuotationItemSerializer,
    ProformaInvoiceSerializer,
    ProformaInvoiceCreateSerializer,
    ProformaInvoiceUpdateSerializer,
)

LOCK_TIMEOUT_MINUTES = 30


class ClientQueryViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Client Query CRUD operations
    Features:
    - Upload PDF files with client queries
    - Track query status
    - Link to quotations
    """
    permission_classes = [SalesModulePermission]
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
    permission_classes = [SalesModulePermission]
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
    permission_classes = [SalesModulePermission]
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


# ═════════════════════════════════════════════════════════════════════════════
# Proforma Invoice ViewSet
# ═════════════════════════════════════════════════════════════════════════════

class ProformaInvoiceViewSet(viewsets.ModelViewSet):
    permission_classes = [SalesModulePermission]
    queryset = ProformaInvoice.objects.all().select_related(
        'requisition', 'created_by', 'locked_by'
    ).prefetch_related('items__product')
    serializer_class = ProformaInvoiceSerializer

    filter_backends  = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['requisition', 'status', 'currency']
    search_fields    = ['pi_number', 'requisition__requisition_number']
    ordering         = ['-pi_number']

    def get_serializer_class(self):
        if self.action == 'create':
            return ProformaInvoiceCreateSerializer
        if self.action in ('update', 'partial_update'):
            return ProformaInvoiceUpdateSerializer
        return ProformaInvoiceSerializer

    def perform_create(self, serializer):
        pi = serializer.save(created_by=self.request.user)
        AuditLog.log(self.request.user, 'CREATE', pi, {
            'pi_number': pi.pi_number,
            'requisition': pi.requisition.requisition_number if pi.requisition else 'STOCK SALE',
            'currency': pi.currency,
            'grand_total': str(pi.grand_total),
        })

    # ── Edit with revision tracking ──────────────────────────────────────

    def perform_update(self, serializer):
        pi = serializer.instance

        if pi.locked_by and pi.locked_by != self.request.user:
            if pi.locked_at and (timezone.now() - pi.locked_at) < timedelta(minutes=LOCK_TIMEOUT_MINUTES):
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied(
                    f'PI is locked for editing by {pi.locked_by.get_full_name()}'
                )

        old_values = {
            'pi_number': pi.pi_number,
            'revision_number': pi.revision_number,
            'grand_total': str(pi.grand_total),
        }

        pi.revision_number += 1
        pi.is_revised = True
        if not pi.pi_number.endswith('R'):
            pi.pi_number = pi.pi_number + 'R'

        serializer.save()
        pi.refresh_from_db()

        AuditLog.log(self.request.user, 'UPDATE', pi, {
            'old': old_values,
            'new': {
                'pi_number': pi.pi_number,
                'revision_number': pi.revision_number,
                'grand_total': str(pi.grand_total),
            },
        })

    # ── Lock / Unlock ────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def lock(self, request, pk=None):
        pi = self.get_object()
        if pi.locked_by and pi.locked_by != request.user:
            if pi.locked_at and (timezone.now() - pi.locked_at) < timedelta(minutes=LOCK_TIMEOUT_MINUTES):
                return Response(
                    {
                        'error': 'PI is currently being edited by another user',
                        'locked_by': pi.locked_by.get_full_name(),
                        'locked_at': pi.locked_at.isoformat(),
                    },
                    status=status.HTTP_409_CONFLICT,
                )
        ProformaInvoice.objects.filter(pk=pi.pk).update(
            locked_by=request.user, locked_at=timezone.now(),
        )
        pi.refresh_from_db()
        return Response({
            'message': 'PI locked for editing',
            'pi_number': pi.pi_number,
            'locked_by': request.user.get_full_name(),
            'locked_at': pi.locked_at.isoformat(),
        })

    @action(detail=True, methods=['post'])
    def unlock(self, request, pk=None):
        pi = self.get_object()
        if pi.locked_by and pi.locked_by != request.user and request.user.role != 'ADMIN':
            return Response(
                {'error': 'Only the lock holder or an admin can unlock'},
                status=status.HTTP_403_FORBIDDEN,
            )
        ProformaInvoice.objects.filter(pk=pi.pk).update(locked_by=None, locked_at=None)
        return Response({'message': 'PI unlocked', 'pi_number': pi.pi_number})

    # ── Status transitions ─────────────────────────────────────────────

    ALLOWED_TRANSITIONS = {
        'DRAFT': ['SENT', 'CANCELLED'],
        'SENT': ['ACCEPTED', 'CANCELLED'],
        'ACCEPTED': ['CANCELLED'],
        'CANCELLED': [],
    }

    def _change_status(self, request, pi, new_status):
        allowed = self.ALLOWED_TRANSITIONS.get(pi.status, [])
        if new_status not in allowed:
            return Response(
                {
                    'error': f'Cannot move from {pi.status} to {new_status}',
                    'current_status': pi.status,
                    'allowed_transitions': allowed,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        old_status = pi.status
        pi.status = new_status
        pi.save()
        AuditLog.log(request.user, 'STATUS_CHANGE', pi, {
            'pi_number': pi.pi_number,
            'old_status': old_status,
            'new_status': new_status,
        })
        return Response({
            'message': f'PI status changed to {new_status}',
            'pi': ProformaInvoiceSerializer(pi).data,
        })

    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        pi = self.get_object()
        return self._change_status(request, pi, 'SENT')

    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        from datetime import date
        from django.db import transaction as db_transaction
        from inventory.models import Product

        pi = self.get_object()
        allowed = self.ALLOWED_TRANSITIONS.get(pi.status, [])
        if 'ACCEPTED' not in allowed:
            return Response(
                {'error': f'Cannot move from {pi.status} to ACCEPTED', 'current_status': pi.status, 'allowed_transitions': allowed},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with db_transaction.atomic():
            product_ids = list(pi.items.values_list('product_id', flat=True))
            locked_products = {
                p.id: p for p in Product.objects.select_for_update().filter(id__in=product_ids)
            }

            insufficient = []
            for item in pi.items.select_related('product').all():
                product = locked_products[item.product_id]
                if product.current_stock < item.quantity:
                    insufficient.append({
                        'product': product.item_name,
                        'product_code': product.item_code,
                        'available': float(product.current_stock),
                        'required': float(item.quantity),
                    })
            if insufficient:
                return Response(
                    {'error': 'Insufficient stock to accept PI', 'insufficient_items': insufficient},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            old_status = pi.status
            pi.status = 'ACCEPTED'
            pi.save()

            for item in pi.items.all():
                product = locked_products[item.product_id]
                product.current_stock -= item.quantity
                product.sale_count += 1
                product.total_sold_qty += item.quantity
                product.last_sale_date = date.today()
                product.save()

        AuditLog.log(request.user, 'STATUS_CHANGE', pi, {
            'pi_number': pi.pi_number, 'old_status': old_status, 'new_status': 'ACCEPTED',
        })
        return Response({'message': 'PI accepted — stock updated', 'pi': ProformaInvoiceSerializer(pi).data})

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        from django.db import transaction as db_transaction

        password_error = check_password_confirmation(request)
        if password_error:
            return password_error

        pi = self.get_object()
        allowed = self.ALLOWED_TRANSITIONS.get(pi.status, [])
        if 'CANCELLED' not in allowed:
            return Response(
                {'error': f'Cannot move from {pi.status} to CANCELLED', 'current_status': pi.status, 'allowed_transitions': allowed},
                status=status.HTTP_400_BAD_REQUEST,
            )

        was_accepted = pi.status == 'ACCEPTED'

        with db_transaction.atomic():
            old_status = pi.status
            pi.status = 'CANCELLED'
            pi.save()

            if was_accepted:
                from inventory.models import Product
                product_ids = list(pi.items.values_list('product_id', flat=True))
                locked_products = {
                    p.id: p for p in Product.objects.select_for_update().filter(id__in=product_ids)
                }
                for item in pi.items.all():
                    product = locked_products[item.product_id]
                    product.current_stock += item.quantity
                    product.sale_count = max(product.sale_count - 1, 0)
                    product.total_sold_qty = max(product.total_sold_qty - item.quantity, 0)
                    product.save()

        AuditLog.log(request.user, 'STATUS_CHANGE', pi, {
            'pi_number': pi.pi_number, 'old_status': old_status, 'new_status': 'CANCELLED',
            'stock_reversed': was_accepted,
        })
        return Response({'message': f'PI cancelled{" — stock reversed" if was_accepted else ""}', 'pi': ProformaInvoiceSerializer(pi).data})

    # ── Requisition items with purchase status ───────────────────────────

    @action(detail=False, methods=['get'])
    def requisition_items(self, request):
        """
        GET /api/proforma-invoices/requisition_items?requisition=uuid
        Returns requisition items with their purchase status.
        Items not yet purchased (is_received=False) are flagged so frontend can disable them.
        Also shows how much quantity is already allocated to other active PIs.
        """
        from django.db.models import Sum
        from purchase_orders.models import PurchaseOrderItem
        from requisitions.models import RequisitionItem
        from .models import ProformaInvoiceItem

        req_id = request.query_params.get('requisition')
        if not req_id:
            return Response({'error': 'requisition param required'}, status=status.HTTP_400_BAD_REQUEST)

        req_items = RequisitionItem.objects.filter(
            requisition_id=req_id
        ).select_related('product')

        result = []
        for ri in req_items:
            po_item = PurchaseOrderItem.objects.filter(
                po__requisition_id=req_id, product=ri.product,
            ).exclude(po__status='CANCELLED').first()

            if not po_item:
                purchase_status = 'PENDING'
                can_add_to_pi = False
            elif po_item.is_received:
                purchase_status = 'COMPLETED'
                can_add_to_pi = True
            else:
                purchase_status = 'PO_CREATED'
                can_add_to_pi = False

            already_in_pi = ProformaInvoiceItem.objects.filter(
                proforma_invoice__requisition_id=req_id,
                product=ri.product,
            ).exclude(
                proforma_invoice__status='CANCELLED'
            ).aggregate(total=Sum('quantity'))['total'] or 0

            purchased_qty = PurchaseOrderItem.objects.filter(
                po__requisition_id=req_id,
                product=ri.product,
                is_received=True,
            ).exclude(po__status='CANCELLED').aggregate(
                total=Sum('quantity')
            )['total'] or 0

            remaining_qty = max(float(purchased_qty) - float(already_in_pi), 0)

            if can_add_to_pi and remaining_qty <= 0:
                can_add_to_pi = False
                purchase_status = 'FULLY_ALLOCATED'

            result.append({
                'requisition_item_id': str(ri.id),
                'product_id': str(ri.product.id),
                'product_code': ri.product.item_code,
                'product_name': ri.product.item_name,
                'hsn_code': ri.product.hsn_code,
                'unit': ri.product.unit,
                'quantity': float(ri.quantity),
                'already_in_pi': float(already_in_pi),
                'remaining_qty': remaining_qty,
                'current_stock': float(ri.product.current_stock),
                'purchase_status': purchase_status,
                'can_add_to_pi': can_add_to_pi,
            })

        return Response({'items': result})

    @action(detail=False, methods=['get'])
    def stock_items(self, request):
        """
        GET /api/proforma-invoices/stock_items
        Returns products with stock > 0 for direct/stock sale PI (no requisition).
        Includes purchase history — which requisitions the product was bought under.
        """
        from inventory.models import Product
        from purchase_orders.models import PurchaseOrderItem

        products = Product.objects.filter(
            is_active=True, current_stock__gt=0
        ).order_by('item_name')

        result = []
        for p in products:
            po_items = PurchaseOrderItem.objects.filter(
                product=p, is_received=True,
            ).exclude(po__status='CANCELLED').select_related(
                'po__requisition'
            ).order_by('-po__po_date')

            purchase_history = []
            seen_reqs = set()
            for poi in po_items:
                req = poi.po.requisition
                if req and req.id not in seen_reqs:
                    seen_reqs.add(req.id)
                    purchase_history.append({
                        'requisition_number': req.requisition_number,
                        'po_number': poi.po.po_number,
                        'qty': float(poi.quantity),
                        'rate': float(poi.rate),
                    })

            result.append({
                'product_id': str(p.id),
                'product_code': p.item_code,
                'product_name': p.item_name,
                'unit': p.unit,
                'current_stock': float(p.current_stock),
                'rate': float(p.rate),
                'purchase_history': purchase_history,
            })

        return Response({'items': result})
