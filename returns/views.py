from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db import transaction as db_transaction
from datetime import datetime

from core.permissions import ReturnsModulePermission
from audit_logs.models import AuditLog
from .models import SalesReturn, PurchaseReturn
from .serializers import (
    SalesReturnSerializer, SalesReturnCreateSerializer,
    PurchaseReturnSerializer, PurchaseReturnCreateSerializer,
)


class SalesReturnViewSet(viewsets.ModelViewSet):
    permission_classes = [ReturnsModulePermission]
    queryset = SalesReturn.objects.all().select_related(
        'proforma_invoice', 'created_by', 'approved_by'
    ).prefetch_related('items__product')

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['proforma_invoice', 'status']
    search_fields = ['return_number', 'proforma_invoice__pi_number', 'reason']
    ordering = ['-return_number']

    def get_serializer_class(self):
        if self.action == 'create':
            return SalesReturnCreateSerializer
        return SalesReturnSerializer

    def perform_create(self, serializer):
        sr = serializer.save(created_by=self.request.user)
        AuditLog.log(self.request.user, 'CREATE', sr, {
            'return_number': sr.return_number,
            'pi_number': sr.proforma_invoice.pi_number,
            'total': str(sr.total_return_amount),
        })

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        sr = self.get_object()
        if sr.status != 'DRAFT':
            return Response(
                {'error': f'Cannot approve — current status is {sr.status}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with db_transaction.atomic():
            from inventory.models import Product
            product_ids = list(sr.items.values_list('product_id', flat=True))
            locked_products = {
                p.id: p for p in Product.objects.select_for_update().filter(id__in=product_ids)
            }

            sr.status = 'APPROVED'
            sr.approved_by = request.user
            sr.approved_at = timezone.now()

            year = datetime.now().year
            prefix = f'EEL/CN/{year}'
            last_cn = SalesReturn.objects.filter(
                credit_note_number__startswith=prefix + '/'
            ).order_by('-credit_note_number').first()
            cn_num = 1
            if last_cn and last_cn.credit_note_number:
                try:
                    cn_num = int(last_cn.credit_note_number.split('/')[-1]) + 1
                except ValueError:
                    pass
            sr.credit_note_number = f'{prefix}/{cn_num:04d}'
            sr.save()

            for item in sr.items.all():
                product = locked_products[item.product_id]
                if item.condition != 'UNUSABLE':
                    product.current_stock += item.quantity
                product.total_sold_qty = max(product.total_sold_qty - item.quantity, 0)
                product.save()

        AuditLog.log(request.user, 'APPROVE', sr, {
            'return_number': sr.return_number,
            'credit_note': sr.credit_note_number,
            'items_count': sr.items.count(),
        })
        return Response({
            'message': f'Sales return approved — Credit Note {sr.credit_note_number} generated',
            'data': SalesReturnSerializer(sr).data,
        })

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        sr = self.get_object()
        if sr.status == 'CANCELLED':
            return Response({'error': 'Already cancelled'}, status=status.HTTP_400_BAD_REQUEST)

        was_approved = sr.status == 'APPROVED'

        with db_transaction.atomic():
            if was_approved:
                from inventory.models import Product
                product_ids = list(sr.items.values_list('product_id', flat=True))
                locked_products = {
                    p.id: p for p in Product.objects.select_for_update().filter(id__in=product_ids)
                }
                for item in sr.items.all():
                    product = locked_products[item.product_id]
                    if item.condition != 'UNUSABLE':
                        product.current_stock -= item.quantity
                    product.total_sold_qty += item.quantity
                    product.save()

            sr.status = 'CANCELLED'
            sr.save()

        AuditLog.log(request.user, 'CANCEL', sr, {
            'return_number': sr.return_number,
            'stock_reversed': was_approved,
        })
        return Response({
            'message': f'Sales return cancelled{" — stock reversed" if was_approved else ""}',
            'data': SalesReturnSerializer(sr).data,
        })

    @action(detail=False, methods=['get'])
    def pi_items(self, request):
        """Items from a PI that can be returned (with already-returned quantities)."""
        from sales.models import ProformaInvoiceItem
        from .models import SalesReturnItem
        from django.db.models import Sum
        from decimal import Decimal

        pi_id = request.query_params.get('proforma_invoice')
        if not pi_id:
            return Response({'error': 'proforma_invoice param required'}, status=status.HTTP_400_BAD_REQUEST)

        pi_items = ProformaInvoiceItem.objects.filter(
            proforma_invoice_id=pi_id
        ).select_related('product')

        result = []
        for pii in pi_items:
            already_returned = SalesReturnItem.objects.filter(
                sales_return__proforma_invoice_id=pi_id,
                product=pii.product,
            ).exclude(
                sales_return__status='CANCELLED'
            ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')

            returnable = pii.quantity - already_returned
            result.append({
                'product_id': str(pii.product.id),
                'product_code': pii.product.item_code,
                'product_name': pii.product.item_name,
                'unit': pii.product.unit,
                'sold_qty': float(pii.quantity),
                'unit_price': float(pii.unit_price),
                'already_returned': float(already_returned),
                'returnable_qty': float(max(returnable, Decimal('0'))),
            })

        return Response({'items': result})


class PurchaseReturnViewSet(viewsets.ModelViewSet):
    permission_classes = [ReturnsModulePermission]
    queryset = PurchaseReturn.objects.all().select_related(
        'purchase_order__vendor', 'created_by', 'approved_by'
    ).prefetch_related('items__product')

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['purchase_order', 'status']
    search_fields = ['return_number', 'purchase_order__po_number', 'reason']
    ordering = ['-return_number']

    def get_serializer_class(self):
        if self.action == 'create':
            return PurchaseReturnCreateSerializer
        return PurchaseReturnSerializer

    def perform_create(self, serializer):
        pr = serializer.save(created_by=self.request.user)
        AuditLog.log(self.request.user, 'CREATE', pr, {
            'return_number': pr.return_number,
            'po_number': pr.purchase_order.po_number,
            'total': str(pr.total_return_amount),
        })

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        pr = self.get_object()
        if pr.status != 'DRAFT':
            return Response(
                {'error': f'Cannot approve — current status is {pr.status}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with db_transaction.atomic():
            from inventory.models import Product
            product_ids = list(pr.items.values_list('product_id', flat=True))
            locked_products = {
                p.id: p for p in Product.objects.select_for_update().filter(id__in=product_ids)
            }

            insufficient = []
            for item in pr.items.all():
                product = locked_products[item.product_id]
                if product.current_stock < item.quantity:
                    insufficient.append({
                        'product': product.item_name,
                        'available': float(product.current_stock),
                        'returning': float(item.quantity),
                    })

            if insufficient:
                return Response(
                    {'error': 'Insufficient stock to return', 'insufficient_items': insufficient},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            pr.status = 'APPROVED'
            pr.approved_by = request.user
            pr.approved_at = timezone.now()

            year = datetime.now().year
            prefix = f'EEL/DN/{year}'
            last_dn = PurchaseReturn.objects.filter(
                debit_note_number__startswith=prefix + '/'
            ).order_by('-debit_note_number').first()
            dn_num = 1
            if last_dn and last_dn.debit_note_number:
                try:
                    dn_num = int(last_dn.debit_note_number.split('/')[-1]) + 1
                except ValueError:
                    pass
            pr.debit_note_number = f'{prefix}/{dn_num:04d}'
            pr.save()

            for item in pr.items.all():
                product = locked_products[item.product_id]
                product.current_stock -= item.quantity
                product.total_purchased_qty = max(product.total_purchased_qty - item.quantity, 0)
                product.save()

        AuditLog.log(request.user, 'APPROVE', pr, {
            'return_number': pr.return_number,
            'debit_note': pr.debit_note_number,
            'items_count': pr.items.count(),
        })
        return Response({
            'message': f'Purchase return approved — Debit Note {pr.debit_note_number} generated',
            'data': PurchaseReturnSerializer(pr).data,
        })

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        pr = self.get_object()
        if pr.status == 'CANCELLED':
            return Response({'error': 'Already cancelled'}, status=status.HTTP_400_BAD_REQUEST)

        was_approved = pr.status == 'APPROVED'

        with db_transaction.atomic():
            if was_approved:
                from inventory.models import Product
                product_ids = list(pr.items.values_list('product_id', flat=True))
                locked_products = {
                    p.id: p for p in Product.objects.select_for_update().filter(id__in=product_ids)
                }
                for item in pr.items.all():
                    product = locked_products[item.product_id]
                    product.current_stock += item.quantity
                    product.total_purchased_qty += item.quantity
                    product.save()

            pr.status = 'CANCELLED'
            pr.save()

        AuditLog.log(request.user, 'CANCEL', pr, {
            'return_number': pr.return_number,
            'stock_reversed': was_approved,
        })
        return Response({
            'message': f'Purchase return cancelled{" — stock restored" if was_approved else ""}',
            'data': PurchaseReturnSerializer(pr).data,
        })

    @action(detail=False, methods=['get'])
    def po_items(self, request):
        """Items from a PO that can be returned (with already-returned quantities)."""
        from purchase_orders.models import PurchaseOrderItem
        from .models import PurchaseReturnItem
        from django.db.models import Sum
        from decimal import Decimal

        po_id = request.query_params.get('purchase_order')
        if not po_id:
            return Response({'error': 'purchase_order param required'}, status=status.HTTP_400_BAD_REQUEST)

        po_items = PurchaseOrderItem.objects.filter(
            po_id=po_id, is_received=True
        ).select_related('product')

        result = []
        for poi in po_items:
            already_returned = PurchaseReturnItem.objects.filter(
                purchase_return__purchase_order_id=po_id,
                product=poi.product,
            ).exclude(
                purchase_return__status='CANCELLED'
            ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')

            returnable = poi.quantity - already_returned
            result.append({
                'product_id': str(poi.product.id),
                'product_code': poi.product.item_code,
                'product_name': poi.product.item_name,
                'unit': poi.product.unit,
                'received_qty': float(poi.quantity),
                'unit_price': float(poi.rate),
                'already_returned': float(already_returned),
                'returnable_qty': float(max(returnable, Decimal('0'))),
            })

        return Response({'items': result})
