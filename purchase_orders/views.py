from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from .models import PurchaseOrder, PurchaseOrderItem
from .serializers import PurchaseOrderSerializer, GeneratePOSerializer

class PurchaseOrderViewSet(viewsets.ModelViewSet):
    """
    Purchase Order APIs

    list: Get all POs
    retrieve: Get single PO
    generate_from_comparison: Create PO from selections
    mark_item_purchased: Update stock when item received
    """
    queryset = PurchaseOrder.objects.all().select_related(
        'requisition', 'vendor', 'created_by'
    ).prefetch_related('items__product')
    serializer_class = PurchaseOrderSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['requisition', 'vendor', 'status']
    search_fields = ['po_number', 'vendor__vendor_name']
    ordering = ['-po_number']

    @action(detail=False, methods=['post'])
    def generate_from_comparison(self, request):
        """
        Generate PO from comparison selections

        POST /api/purchase-orders/generate_from_comparison
        {
        "requisition": "uuid",
        "po_date": "2026-01-22",
        "selections": [
            "quotation-item-uuid-1",
            "quotation-item-uuid-2"
        ]
        }
        """
        serializer = GeneratePOSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pos = serializer.save(created_by=request.user)

        representation_serializer = PurchaseOrderSerializer(pos, many=True)

        return Response({
            'message': f'{len(pos)} Purchase Order(s) created',
            'purchase_orders': representation_serializer.data
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def mark_item_purchased(self, request, pk=None):
        """
        Mark item as purchased - updates stock!

        POST /api/purchase-orders/{po_id}/mark_item_purchased
        {
          "item_id": "uuid"
        }
        """
        po = self.get_object()
        item_id = request.data.get('item_id')

        if not item_id:
            return Response({'error': 'item_id required'},
                          status=status.HTTP_400_BAD_REQUEST)

        try:
            item = po.items.get(id=item_id)
        except PurchaseOrderItem.DoesNotExist:
            return Response({'error': 'Item not found'},
                          status=status.HTTP_404_NOT_FOUND)

        if item.is_received:
            return Response({'error': 'Already received'},
                          status=status.HTTP_400_BAD_REQUEST)

        item.mark_as_purchased()

        return Response({
            'message': 'Item marked as purchased',
            'product': item.product.item_name,
            'quantity': item.quantity,
            'new_stock': item.product.current_stock,
            'po_status': po.status
        })

    @action(detail=True, methods=['post'])
    def mark_all_purchased(self, request, pk=None):
        """Mark all items purchased"""
        po = self.get_object()

        for item in po.items.filter(is_received=False):
            item.mark_as_purchased()

        po.refresh_from_db()

        return Response({
            'message': 'All items marked as purchased',
            'po_status': po.status
        })
