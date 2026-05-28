from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from datetime import timedelta

from .models import PurchaseOrder, PurchaseOrderItem
from .serializers import PurchaseOrderSerializer, PurchaseOrderUpdateSerializer, GeneratePOSerializer
from core.password_confirm import check_password_confirmation
from core.permissions import PurchaseModulePermission
from audit_logs.models import AuditLog

LOCK_TIMEOUT_MINUTES = 30


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    permission_classes = [PurchaseModulePermission]
    queryset = PurchaseOrder.objects.all().select_related(
        'requisition', 'vendor', 'created_by', 'cancelled_by', 'locked_by'
    ).prefetch_related('items__product')
    serializer_class = PurchaseOrderSerializer

    def get_serializer_class(self):
        if self.action in ('update', 'partial_update'):
            return PurchaseOrderUpdateSerializer
        return PurchaseOrderSerializer
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['requisition', 'vendor', 'status']
    search_fields    = ['po_number', 'vendor__vendor_name']
    ordering         = ['-po_number']

    # ───────────────────────────────────────────────────────────────────────
    # Create PO from quotation comparison
    # ───────────────────────────────────────────────────────────────────────

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

        for po in pos:
            AuditLog.log(request.user, 'CREATE', po, {
                'po_number': po.po_number,
                'vendor': po.vendor.vendor_name,
                'total_amount': str(po.total_amount),
                'currency': po.currency,
            })

        return Response(
            {
                'message':         f'{len(pos)} Purchase Order(s) created',
                'purchase_orders': PurchaseOrderSerializer(pos, many=True).data,
            },
            status=status.HTTP_201_CREATED,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Receive a single item
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

        # FIX: Refresh po from DB so po.status reflects the update_status()
        # call that happened inside mark_as_purchased().
        # Previously this was stale — if this was the last item, the response
        # would show PARTIALLY_RECEIVED even though the DB had COMPLETED.
        po.refresh_from_db()

        return Response({
            'message':   'Item marked as received',
            'product':   item.product.item_name,
            'quantity':  float(item.quantity),
            'new_stock': float(item.product.current_stock),
            'po_status': po.status,   # ← now always correct
        })

    # ──────────────────────────────────────────────────────────────────────────
    # Receive all items
    # ──────────────────────────────────────────────────────────────────────────

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

        # Refresh to get the final status written by update_status()
        po.refresh_from_db()
        return Response({
            'message':   'All items marked as received',
            'po_status': po.status,
        })

    # ──────────────────────────────────────────────────────────────────────────
    # Cancel  — password protected
    # ──────────────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """
        Cancel a Purchase Order.

        ⚠️  SENSITIVE ACTION — requires confirm_password in the request body.

        POST /api/purchase-orders/{id}/cancel
        {
            "confirm_password": "<your password>",          ← required
            "reason":           "Vendor could not supply"   // optional
        }

        Rules
        -----
        • CANCELLED POs → error (already cancelled)
        • COMPLETED POs → error (all stock already received — cannot reverse)
        • PENDING POs   → cancelled directly, no stock change needed
        • PARTIALLY_RECEIVED POs → received items' stock is REVERSED,
          then PO is cancelled

        Response includes a list of items whose stock was reversed.
        """
        # ── password gate ──────────────────────────────────────────────────
        password_error = check_password_confirmation(request)
        if password_error:
            return password_error

        po     = self.get_object()
        reason = request.data.get('reason', '')

        try:
            reversed_items = po.cancel(cancelled_by_user=request.user, reason=reason)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        AuditLog.log(request.user, 'UPDATE', po, {
            'action': 'CANCEL',
            'reason': po.cancellation_reason,
            'stock_reversed': reversed_items,
        })

        serializer = self.get_serializer(po)
        return Response({
            'message':        'Purchase order cancelled successfully',
            'po_number':      po.po_number,
            'status':         po.status,
            'cancelled_by':   request.user.get_full_name(),
            'cancelled_at':   po.cancelled_at.isoformat(),
            'reason':         po.cancellation_reason,
            'stock_reversed': reversed_items,
            'purchase_order': serializer.data,
        })

    # ──────────────────────────────────────────────────────────────────────────
    # Edit locking
    # ──────────────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def lock(self, request, pk=None):
        """Acquire edit lock on a PO."""
        po = self.get_object()

        if po.locked_by and po.locked_by != request.user:
            if po.locked_at and (timezone.now() - po.locked_at) < timedelta(minutes=LOCK_TIMEOUT_MINUTES):
                return Response(
                    {
                        'error': 'PO is currently being edited by another user',
                        'locked_by': po.locked_by.get_full_name(),
                        'locked_at': po.locked_at.isoformat(),
                    },
                    status=status.HTTP_409_CONFLICT,
                )

        PurchaseOrder.objects.filter(pk=po.pk).update(
            locked_by=request.user,
            locked_at=timezone.now(),
        )
        po.refresh_from_db()
        return Response({
            'message': 'PO locked for editing',
            'po_number': po.po_number,
            'locked_by': request.user.get_full_name(),
            'locked_at': po.locked_at.isoformat(),
        })

    @action(detail=True, methods=['post'])
    def unlock(self, request, pk=None):
        """Release edit lock on a PO."""
        po = self.get_object()

        if po.locked_by and po.locked_by != request.user and request.user.role != 'ADMIN':
            return Response(
                {'error': 'Only the lock holder or an admin can unlock'},
                status=status.HTTP_403_FORBIDDEN,
            )

        PurchaseOrder.objects.filter(pk=po.pk).update(
            locked_by=None,
            locked_at=None,
        )
        return Response({'message': 'PO unlocked', 'po_number': po.po_number})

    # ──────────────────────────────────────────────────────────────────────────
    # PO Edit with revision tracking
    # ──────────────────────────────────────────────────────────────────────────

    def perform_update(self, serializer):
        po = serializer.instance

        if po.locked_by and po.locked_by != self.request.user:
            if po.locked_at and (timezone.now() - po.locked_at) < timedelta(minutes=LOCK_TIMEOUT_MINUTES):
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied(
                    f'PO is locked for editing by {po.locked_by.get_full_name()}'
                )

        old_values = {
            'po_number': po.po_number,
            'remarks': po.remarks,
            'revision_number': po.revision_number,
            'items_total': str(po.items_total),
            'discount_amount': str(po.discount_amount),
            'total_amount': str(po.total_amount),
        }

        po.revision_number += 1
        po.is_revised = True
        if not po.po_number.endswith('R'):
            po.po_number = po.po_number + 'R'

        serializer.save()
        po.refresh_from_db()

        AuditLog.log(self.request.user, 'UPDATE', po, {
            'old': old_values,
            'new': {
                'po_number': po.po_number,
                'remarks': po.remarks,
                'revision_number': po.revision_number,
                'items_total': str(po.items_total),
                'discount_amount': str(po.discount_amount),
                'total_amount': str(po.total_amount),
            },
        })

    # ──────────────────────────────────────────────────────────────────────────
    # Update GST on PO
    # ──────────────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def update_gst(self, request, pk=None):
        """Update GST percentages and recalculate totals."""
        po = self.get_object()
        cgst = request.data.get('cgst_percentage')
        sgst = request.data.get('sgst_percentage')
        igst = request.data.get('igst_percentage')

        if cgst is not None:
            po.cgst_percentage = cgst
        if sgst is not None:
            po.sgst_percentage = sgst
        if igst is not None:
            po.igst_percentage = igst
        po.save()
        po.calculate_total()
        return Response(PurchaseOrderSerializer(po).data)
