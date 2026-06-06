from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db import models

from .models import Product
from .serializers import ProductSerializer
from core.password_confirm import PasswordConfirmDestroyMixin
from core.permissions import MasterModulePermission


class ProductViewSet(PasswordConfirmDestroyMixin, viewsets.ModelViewSet):
    permission_classes = [MasterModulePermission]
    """
    ViewSet for Product CRUD operations

    list:           GET    /api/products
    create:         POST   /api/products
    retrieve:       GET    /api/products/{id}
    update:         PUT    /api/products/{id}
    partial_update: PATCH  /api/products/{id}
    destroy:        DELETE /api/products/{id}  ⚠ requires confirm_password in body

    Custom:
        GET /api/products/low_stock  – products at or below reorder level
        GET /api/products/active     – active products only

    DELETE body
    -----------
    {
        "confirm_password": "<your password>"
    }
    """
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active', 'unit', 'requisition_number']
    search_fields = ['item_code', 'item_name', 'hsn_code', 'description', 'requisition_number']
    ordering_fields = ['item_name', 'created_at', 'current_stock', 'rate']
    ordering = ['-created_at']

    @action(detail=False, methods=['get'])
    def low_stock(self, request):
        """Get products below reorder level"""
        low_stock_products = self.queryset.filter(
            current_stock__lte=models.F('reorder_level'),
            is_active=True
        )
        serializer = self.get_serializer(low_stock_products, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def active(self, request):
        """Get only active products"""
        active_products = self.queryset.filter(is_active=True)
        serializer = self.get_serializer(active_products, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def by_requisition(self, request):
        """Get products linked to a specific requisition number"""
        req_number = request.query_params.get('requisition_number')
        if not req_number:
            return Response(
                {'error': 'requisition_number parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        products = self.queryset.filter(requisition_number=req_number)
        serializer = self.get_serializer(products, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def tracking(self, request, pk=None):
        """Full lifecycle: all requisitions, POs, PIs for this product"""
        from purchase_orders.models import PurchaseOrderItem
        from sales.models import ProformaInvoiceItem

        product = self.get_object()

        purchases = PurchaseOrderItem.objects.filter(
            product=product, is_received=True
        ).exclude(po__status='CANCELLED').select_related(
            'po__requisition', 'po__vendor'
        ).order_by('-po__po_date')

        purchase_history = []
        for poi in purchases:
            conv = float(poi.po.conversion_rate or 1)
            if poi.po.currency == 'INR':
                conv = 1
            purchase_history.append({
                'requisition_number': poi.po.requisition.requisition_number,
                'requisition_id': str(poi.po.requisition.id),
                'po_number': poi.po.po_number,
                'po_id': str(poi.po.id),
                'vendor_name': poi.po.vendor.vendor_name,
                'po_date': poi.po.po_date,
                'quantity': float(poi.quantity),
                'rate': float(poi.rate),
                'amount': float(poi.amount),
                'currency': poi.po.currency,
                'conversion_rate': conv,
                'amount_inr': round(float(poi.amount) * conv, 2),
            })

        sales = ProformaInvoiceItem.objects.filter(
            product=product
        ).exclude(proforma_invoice__status='CANCELLED').select_related(
            'proforma_invoice__requisition'
        ).order_by('-proforma_invoice__pi_date')

        sale_history = []
        for pii in sales:
            pi = pii.proforma_invoice
            conv = float(pi.conversion_rate or 1)
            if pi.currency == 'INR':
                conv = 1
            sale_history.append({
                'pi_number': pi.pi_number,
                'pi_id': str(pi.id),
                'requisition_number': pi.requisition.requisition_number if pi.requisition else None,
                'is_stock_sale': pi.requisition is None,
                'pi_date': pi.pi_date,
                'status': pi.status,
                'quantity': float(pii.quantity),
                'unit_price': float(pii.unit_price),
                'amount': float(pii.amount),
                'currency': pi.currency,
                'conversion_rate': conv,
                'amount_inr': round(float(pii.amount) * conv, 2),
            })

        return Response({
            'product': {
                'id': str(product.id),
                'item_code': product.item_code,
                'item_name': product.item_name,
                'unit': product.unit,
                'current_stock': float(product.current_stock),
            },
            'total_purchases': len(purchase_history),
            'total_sales': len(sale_history),
            'purchases': purchase_history,
            'sales': sale_history,
        })
