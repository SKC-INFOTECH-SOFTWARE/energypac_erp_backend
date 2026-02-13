from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Sum, F
from decimal import Decimal

from .models import WorkOrder, WorkOrderItem
from .serializers import (
    WorkOrderSerializer,
    WorkOrderCreateSerializer,
    WorkOrderItemSerializer,
    StockAvailabilitySerializer,
    FinancialSummarySerializer,
    DeliverySummarySerializer
)


class WorkOrderViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Work Order CRUD operations

    Features:
    - Create WO from sales quotation (OneToOne - prevents duplicates)
    - Stock availability check for all items
    - Advance payment tracking
    - Delivery progress monitoring
    - Partial delivery support via billing
    """
    queryset = WorkOrder.objects.all().select_related(
        'sales_quotation__client_query', 'created_by'
    ).prefetch_related('items__product')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'sales_quotation', 'wo_date']
    search_fields = ['wo_number', 'client_name', 'sales_quotation__quotation_number']
    ordering_fields = ['wo_date', 'created_at', 'wo_number']
    ordering = ['-wo_number']

    def get_serializer_class(self):
        if self.action == 'create':
            return WorkOrderCreateSerializer
        return WorkOrderSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def destroy(self, request, *args, **kwargs):
        """Prevent deletion - only allow status change"""
        return Response(
            {
                'error': 'Work orders cannot be deleted',
                'message': 'Use status update to CANCELLED instead'
            },
            status=status.HTTP_403_FORBIDDEN
        )

    @action(detail=True, methods=['get'])
    def items_for_billing(self, request, pk=None):
        """
        Get items ready for billing with stock status

        GET /api/work-orders/{id}/items_for_billing

        Returns items with pending quantities and current stock status
        """
        work_order = self.get_object()

        if work_order.status == 'COMPLETED':
            return Response(
                {'error': 'Work order is already completed'},
                status=status.HTTP_400_BAD_REQUEST
            )

        items_data = []
        for item in work_order.items.filter(pending_quantity__gt=0):
            stock_status = item.get_stock_status()

            items_data.append({
                'id': str(item.id),
                'item_code': item.item_code,
                'item_name': item.item_name,
                'description': item.description,
                'hsn_code': item.hsn_code,
                'unit': item.unit,
                'ordered_quantity': float(item.ordered_quantity),
                'delivered_quantity': float(item.delivered_quantity),
                'pending_quantity': float(item.pending_quantity),
                'rate': float(item.rate),
                'stock_status': stock_status
            })

        return Response({
            'wo_number': work_order.wo_number,
            'client_name': work_order.client_name,
            'total_pending_items': len(items_data),
            'items': items_data
        })

    @action(detail=True, methods=['get'])
    def stock_availability(self, request, pk=None):
        """
        Check stock availability for all pending items

        GET /api/work-orders/{id}/stock_availability

        Returns detailed stock status for billing decision
        """
        work_order = self.get_object()

        availability = []
        all_available = True

        for item in work_order.items.filter(pending_quantity__gt=0):
            stock_status = item.get_stock_status()

            availability.append({
                'item_id': str(item.id),
                'item_code': item.item_code,
                'item_name': item.item_name,
                'pending_quantity': float(item.pending_quantity),
                'current_stock': stock_status.get('current_stock', 0),
                'status': stock_status['status'],
                'message': stock_status['message']
            })

            if stock_status['status'] == 'OUT_OF_STOCK':
                all_available = False

        return Response({
            'wo_number': work_order.wo_number,
            'all_items_available': all_available,
            'availability': availability
        })

    @action(detail=True, methods=['get'])
    def financial_summary(self, request, pk=None):
        """
        Get financial summary

        GET /api/work-orders/{id}/financial_summary
        """
        work_order = self.get_object()

        # Calculate pending value
        pending_value = sum(
            item.pending_quantity * item.rate
            for item in work_order.items.all()
        )

        return Response({
            'total_amount': float(work_order.total_amount),
            'advance_amount': float(work_order.advance_amount),
            'advance_deducted': float(work_order.advance_deducted),
            'advance_remaining': float(work_order.advance_remaining),
            'total_delivered_value': float(work_order.total_delivered_value),
            'total_pending_value': float(pending_value)
        })

    @action(detail=True, methods=['get'])
    def delivery_summary(self, request, pk=None):
        """
        Get delivery progress summary

        GET /api/work-orders/{id}/delivery_summary
        """
        work_order = self.get_object()
        items = work_order.items.all()

        total_items = items.count()
        fully_delivered = items.filter(pending_quantity=0).count()
        partially_delivered = items.filter(
            delivered_quantity__gt=0,
            pending_quantity__gt=0
        ).count()
        pending = items.filter(delivered_quantity=0).count()

        # Calculate completion percentage
        total_ordered = sum(item.ordered_quantity for item in items)
        total_delivered = sum(item.delivered_quantity for item in items)

        completion_pct = 0
        if total_ordered > 0:
            completion_pct = round((total_delivered / total_ordered) * 100, 2)

        return Response({
            'total_items': total_items,
            'fully_delivered_items': fully_delivered,
            'partially_delivered_items': partially_delivered,
            'pending_items': pending,
            'completion_percentage': completion_pct
        })

    @action(detail=True, methods=['post'])
    def update_advance(self, request, pk=None):
        """
        Update advance amount

        POST /api/work-orders/{id}/update_advance
        {
            "advance_amount": 50000.00
        }
        """
        work_order = self.get_object()
        advance_amount = request.data.get('advance_amount')

        if advance_amount is None:
            return Response(
                {'error': 'advance_amount is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            advance_amount = Decimal(str(advance_amount))
        except:
            return Response(
                {'error': 'Invalid advance amount'},
                status=status.HTTP_400_BAD_REQUEST
            )

        work_order.advance_amount = advance_amount
        work_order.save()

        serializer = self.get_serializer(work_order)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def by_quotation(self, request):
        """
        Check if work order exists for a quotation

        GET /api/work-orders/by_quotation?quotation={quotation_id}
        """
        quotation_id = request.query_params.get('quotation')

        if not quotation_id:
            return Response(
                {'error': 'quotation parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            work_order = WorkOrder.objects.get(sales_quotation_id=quotation_id)
            serializer = self.get_serializer(work_order)
            return Response({
                'exists': True,
                'work_order': serializer.data
            })
        except WorkOrder.DoesNotExist:
            return Response({
                'exists': False,
                'message': 'No work order found for this quotation'
            })

    @action(detail=False, methods=['get'])
    def active(self, request):
        """
        Get all active (non-completed) work orders

        GET /api/work-orders/active
        """
        active_wos = self.queryset.exclude(status='COMPLETED')
        serializer = self.get_serializer(active_wos, many=True)
        return Response(serializer.data)
