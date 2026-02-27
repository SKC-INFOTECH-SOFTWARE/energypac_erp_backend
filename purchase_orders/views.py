from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from .models import PurchaseOrder, PurchaseOrderItem
from .serializers import PurchaseOrderSerializer, GeneratePOSerializer


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    """
    Purchase Order APIs

    Endpoints
    ---------
    Standard CRUD:
        GET    /api/purchase-orders                  – list all POs
        GET    /api/purchase-orders/{id}             – retrieve PO
        PATCH  /api/purchase-orders/{id}             – partial update

    Custom actions:
        POST   /api/purchase-orders/generate_from_comparison   – create PO from selections
        POST   /api/purchase-orders/{id}/mark_item_purchased   – receive one item into stock
        POST   /api/purchase-orders/{id}/mark_all_purchased    – receive all items into stock
        POST   /api/purchase-orders/{id}/cancel                – cancel PO  ← NEW
    """
    queryset = PurchaseOrder.objects.all().select_related(
        'requisition', 'vendor', 'created_by', 'cancelled_by'
    ).prefetch_related('items__product')
    serializer_class = PurchaseOrderSerializer
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['requisition', 'vendor', 'status']
    search_fields    = ['po_number', 'vendor__vendor_name']
    ordering         = ['-po_number']

    # ──────────────────────────────────────────────────────────────────────────
    # Create PO from quotation comparison
    # ──────────────────────────────────────────────────────────────────────────

    @action(detail=False, methods=['post'])
    def generate_from_comparison(self, request):
        """
        Generate PO(s) from comparison selections (one PO per vendor).

        POST /api/purchase-orders/generate_from_comparison
        {
            "requisition": "uuid",
            "po_date":     "2026-01-22",
            "selections":  ["quotation-item-uuid-1", "quotation-item-uuid-2"]
        }
        """
        serializer = GeneratePOSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pos = serializer.save(created_by=request.user)

        return Response(
            {
                'message':         f'{len(pos)} Purchase Order(s) created',
                'purchase_orders': PurchaseOrderSerializer(pos, many=True).data,
            },
            status=status.HTTP_201_CREATED,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Receive items
    # ──────────────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def mark_item_purchased(self, request, pk=None):
        """
        Mark one item as received — updates stock.

        POST /api/purchase-orders/{id}/mark_item_purchased
        {"item_id": "uuid"}
        """
        po      = self.get_object()
        item_id = request.data.get('item_id')

        if not item_id:
            return Response(
                {'error': 'item_id is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            item = po.items.get(id=item_id)
        except PurchaseOrderItem.DoesNotExist:
            return Response({'error': 'Item not found'}, status=status.HTTP_404_NOT_FOUND)

        if item.is_received:
            return Response({'error': 'Item already received'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            item.mark_as_purchased()
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'message':   'Item marked as received',
            'product':   item.product.item_name,
            'quantity':  item.quantity,
            'new_stock': item.product.current_stock,
            'po_status': po.status,
        })

    @action(detail=True, methods=['post'])
    def mark_all_purchased(self, request, pk=None):
        """
        Mark ALL pending items as received.

        POST /api/purchase-orders/{id}/mark_all_purchased
        """
        po = self.get_object()

        if po.status == 'CANCELLED':
            return Response(
                {'error': 'Cannot receive items on a cancelled purchase order'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        for item in po.items.filter(is_received=False):
            item.mark_as_purchased()

        po.refresh_from_db()
        return Response({
            'message':   'All items marked as received',
            'po_status': po.status,
        })

    # ──────────────────────────────────────────────────────────────────────────
    # Cancel  ← NEW
    # ──────────────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """
        Cancel a Purchase Order.

        POST /api/purchase-orders/{id}/cancel
        {
            "reason": "Vendor could not supply on time"   // optional
        }

        Rules
        -----
        • CANCELLED POs → error (already cancelled)
        • COMPLETED POs → error (all stock already received — cannot reverse)
        • PENDING POs   → cancelled directly, no stock change needed
        • PARTIALLY_RECEIVED POs → received items' stock is REVERSED,
          then PO is cancelled

        Response includes a list of items whose stock was reversed
        so the frontend can show exactly what changed.
        """
        po     = self.get_object()
        reason = request.data.get('reason', '')

        try:
            reversed_items = po.cancel(cancelled_by_user=request.user, reason=reason)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(po)
        return Response({
            'message':       'Purchase order cancelled successfully',
            'po_number':     po.po_number,
            'status':        po.status,
            'cancelled_by':  request.user.get_full_name(),
            'cancelled_at':  po.cancelled_at.isoformat(),
            'reason':        po.cancellation_reason,
            'stock_reversed': reversed_items,   # [] if PO was still PENDING
            'purchase_order': serializer.data,
        })
