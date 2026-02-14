from rest_framework import viewsets, status, filters, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
from decimal import Decimal

from .models import Bill, BillItem
from .serializers import (
    BillSerializer,
    BillCreateSerializer,
    BillItemSerializer,
    StockValidationSerializer
)


class BillViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Bill CRUD operations

    Features:
    - Create bills from work orders with partial delivery
    - Automatic stock deduction on bill generation
    - Advance payment auto-deduction
    - Stock validation before billing
    - Payment tracking
    """
    queryset = Bill.objects.all().select_related(
        'work_order', 'created_by'
    ).prefetch_related('items__product')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'work_order', 'bill_date']
    search_fields = ['bill_number', 'client_name', 'work_order__wo_number']
    ordering_fields = ['bill_date', 'created_at', 'bill_number']
    ordering = ['-bill_number']

    def get_serializer_class(self):
        if self.action == 'create':
            return BillCreateSerializer
        elif self.action == 'validate_stock':
            return StockValidationSerializer
        return BillSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def destroy(self, request, *args, **kwargs):
        """Prevent deletion - use cancel instead"""
        return Response(
            {
                'error': 'Bills cannot be deleted',
                'message': 'Use cancel endpoint to cancel bills'
            },
            status=status.HTTP_403_FORBIDDEN
        )

    @action(detail=False, methods=['post'])
    def validate_stock(self, request):
        """
        CRITICAL: Validate stock before bill generation

        POST /api/bills/validate_stock
        {
            "work_order": "uuid",
            "items": [
                {
                    "work_order_item": "uuid",
                    "delivered_quantity": 10.00
                }
            ]
        }

        Returns:
        - Success: {"stock_available": true, "message": "All items available"}
        - Failure: {"stock_available": false, "issues": [...]}
        """
        serializer = self.get_serializer(data=request.data)

        try:
            serializer.is_valid(raise_exception=True)
            return Response({
                'stock_available': True,
                'message': 'All items available for billing'
            })
        except serializers.ValidationError as e:
            if 'stock_validation_failed' in e.detail:
                return Response({
                    'stock_available': False,
                    'issues': e.detail['issues']
                }, status=status.HTTP_400_BAD_REQUEST)
            else:
                return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def mark_paid(self, request, pk=None):
        """
        Mark bill as paid

        POST /api/bills/{id}/mark_paid
        {
            "amount_paid": 45000.00
        }
        """
        bill = self.get_object()
        amount_paid = request.data.get('amount_paid')

        if amount_paid is None:
            return Response(
                {'error': 'amount_paid is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            amount_paid = Decimal(str(amount_paid))
        except (ValueError, TypeError, Exception):
            return Response(
                {'error': 'Invalid amount'},
                status=status.HTTP_400_BAD_REQUEST
            )

        bill.amount_paid = amount_paid
        bill.balance = bill.net_payable - amount_paid

        if bill.balance <= 0:
            bill.status = 'PAID'

        bill.save()

        serializer = self.get_serializer(bill)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def detailed_summary(self, request, pk=None):
        """
        Get detailed bill summary

        GET /api/bills/{id}/detailed_summary
        """
        bill = self.get_object()

        items_data = []
        for item in bill.items.all():
            items_data.append({
                'item_code': item.item_code,
                'item_name': item.item_name,
                'description': item.description,
                'hsn_code': item.hsn_code,
                'ordered_quantity': float(item.ordered_quantity),
                'previously_delivered': float(item.previously_delivered_quantity),
                'delivered_now': float(item.delivered_quantity),
                'pending_after': float(item.pending_quantity),
                'unit': item.unit,
                'rate': float(item.rate),
                'amount': float(item.amount)
            })

        return Response({
            'bill_number': bill.bill_number,
            'bill_date': bill.bill_date,
            'wo_number': bill.work_order.wo_number,
            'client_details': {
                'name': bill.client_name,
                'contact_person': bill.contact_person,
                'phone': bill.phone,
                'email': bill.email,
                'address': bill.address
            },
            'items': items_data,
            'financial': {
                'subtotal': float(bill.subtotal),
                'cgst': {
                    'percentage': float(bill.cgst_percentage),
                    'amount': float(bill.cgst_amount)
                },
                'sgst': {
                    'percentage': float(bill.sgst_percentage),
                    'amount': float(bill.sgst_amount)
                },
                'igst': {
                    'percentage': float(bill.igst_percentage),
                    'amount': float(bill.igst_amount)
                },
                'total_gst': float(
                    bill.cgst_amount + bill.sgst_amount + bill.igst_amount
                ),
                'total_amount': float(bill.total_amount),
                'advance_deducted': float(bill.advance_deducted),
                'net_payable': float(bill.net_payable),
                'amount_paid': float(bill.amount_paid),
                'balance': float(bill.balance)
            },
            'status': bill.status,
            'remarks': bill.remarks
        })

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def cancel(self, request, pk=None):
        """
        Cancel bill and restore stock

        POST /api/bills/{id}/cancel
        """
        bill = self.get_object()

        if bill.status == 'CANCELLED':
            return Response(
                {'error': 'Bill is already cancelled'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if bill.status == 'PAID':
            return Response(
                {'error': 'Cannot cancel paid bill'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Restore stock
        bill.restore_stock()

        # Update status
        bill.status = 'CANCELLED'
        bill.save()

        serializer = self.get_serializer(bill)
        return Response({
            'message': 'Bill cancelled successfully. Stock has been restored.',
            'bill': serializer.data
        })

    @action(detail=False, methods=['get'])
    def by_work_order(self, request):
        """
        Get all bills for a work order

        GET /api/bills/by_work_order?work_order={wo_id}
        """
        wo_id = request.query_params.get('work_order')

        if not wo_id:
            return Response(
                {'error': 'work_order parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        bills = self.queryset.filter(work_order_id=wo_id)
        serializer = self.get_serializer(bills, many=True)

        return Response({
            'total_bills': bills.count(),
            'bills': serializer.data
        })

    @action(detail=False, methods=['get'])
    def pending_payment(self, request):
        """
        Get all bills with pending payment

        GET /api/bills/pending_payment
        """
        pending_bills = self.queryset.filter(balance__gt=0).exclude(status='CANCELLED')
        serializer = self.get_serializer(pending_bills, many=True)

        total_balance = sum(bill.balance for bill in pending_bills)

        return Response({
            'total_pending_bills': pending_bills.count(),
            'total_balance': float(total_balance),
            'bills': serializer.data
        })
