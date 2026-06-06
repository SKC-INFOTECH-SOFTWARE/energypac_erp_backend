from rest_framework import viewsets, status, filters, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Sum, Count, F, Q
from decimal import Decimal

from core.permissions import TransportModulePermission
from audit_logs.models import AuditLog
from .models import TransportEntry, TransportCostItem
from .serializers import (
    TransportEntrySerializer,
    TransportEntryCreateSerializer,
    TransportEntryUpdateSerializer,
)
from purchase_orders.models import PurchaseOrder
from sales.models import ProformaInvoice


class TransportEntryViewSet(viewsets.ModelViewSet):
    permission_classes = [TransportModulePermission]
    queryset = TransportEntry.objects.all().select_related(
        'purchase_order__vendor', 'created_by'
    ).prefetch_related('cost_items')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['purchase_order', 'proforma_invoice', 'status', 'dispatch_date']
    search_fields = [
        'transport_number', 'transporter_name', 'vehicle_number',
        'purchase_order__po_number', 'purchase_order__vendor__vendor_name',
        'proforma_invoice__pi_number',
    ]
    ordering_fields = ['created_at', 'dispatch_date', 'total_cost']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return TransportEntryCreateSerializer
        if self.action in ('update', 'partial_update'):
            return TransportEntryUpdateSerializer
        return TransportEntrySerializer

    def perform_create(self, serializer):
        entry = serializer.save(created_by=self.request.user)
        ref = entry.purchase_order.po_number if entry.purchase_order else (
            entry.proforma_invoice.pi_number if entry.proforma_invoice else 'N/A'
        )
        AuditLog.log(self.request.user, 'CREATE', entry, {
            'transport_number': entry.transport_number,
            'reference': ref,
            'transporter': entry.transporter_name,
            'total_cost': str(entry.total_cost),
        })

    def perform_update(self, serializer):
        entry = self.get_object()
        if entry.status == 'DELIVERED':
            from rest_framework.exceptions import ValidationError
            raise ValidationError("Cannot edit a delivered transport entry.")
        old_values = {
            'transporter': entry.transporter_name,
            'status': entry.status,
            'total_cost': str(entry.total_cost),
        }
        entry = serializer.save()
        AuditLog.log(self.request.user, 'UPDATE', entry, {
            'old': old_values,
            'new': {
                'transporter': entry.transporter_name,
                'status': entry.status,
                'total_cost': str(entry.total_cost),
            },
        })

    def destroy(self, request, *args, **kwargs):
        return Response(
            {'error': 'Transport entries cannot be deleted (audit trail)'},
            status=status.HTTP_403_FORBIDDEN,
        )

    # ── Landed Cost per PO ───────────────────────────────────────────────
    @action(detail=False, methods=['get'])
    def landed_cost(self, request):
        po_id = request.query_params.get('purchase_order')
        if not po_id:
            return Response(
                {'error': 'purchase_order parameter is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            po = PurchaseOrder.objects.prefetch_related(
                'items__product', 'transport_entries__cost_items'
            ).get(id=po_id)
        except PurchaseOrder.DoesNotExist:
            return Response({'error': 'Purchase order not found'}, status=status.HTTP_404_NOT_FOUND)

        total_transport = sum(
            entry.total_cost for entry in po.transport_entries.all()
        )
        items_total = po.items_total or Decimal('0')

        items_data = []
        for item in po.items.all():
            if items_total > 0:
                value_pct = (item.amount / items_total) * Decimal('100')
                allocated = (item.amount / items_total) * total_transport
            else:
                value_pct = Decimal('0')
                allocated = Decimal('0')

            landed = item.amount + allocated
            landed_rate = landed / item.quantity if item.quantity > 0 else Decimal('0')

            items_data.append({
                'item_id': str(item.id),
                'product_code': item.product.item_code,
                'product_name': item.product.item_name,
                'quantity': float(item.quantity),
                'unit': item.product.unit,
                'purchase_rate': float(item.rate),
                'purchase_amount': float(item.amount),
                'value_percentage': round(float(value_pct), 2),
                'allocated_transport': round(float(allocated), 2),
                'landed_cost': round(float(landed), 2),
                'landed_rate_per_unit': round(float(landed_rate), 2),
            })

        transport_entries = []
        for entry in po.transport_entries.all():
            transport_entries.append({
                'transport_number': entry.transport_number,
                'transporter_name': entry.transporter_name,
                'dispatch_date': entry.dispatch_date,
                'status': entry.status,
                'total_cost': float(entry.total_cost),
                'cost_breakdown': {
                    ci.get_cost_type_display(): float(ci.amount)
                    for ci in entry.cost_items.all()
                },
            })

        return Response({
            'po_number': po.po_number,
            'vendor_name': po.vendor.vendor_name,
            'currency': po.currency,
            'items_total': float(items_total),
            'gst_total': float(po.cgst_amount + po.sgst_amount + po.igst_amount),
            'po_total_amount': float(po.total_amount),
            'total_transport_cost': float(total_transport),
            'grand_total_with_transport': float(po.total_amount + total_transport),
            'transport_entries': transport_entries,
            'items': items_data,
        })

    # ── Transport entries by PI ──────────────────────────────────────────
    @action(detail=False, methods=['get'])
    def by_pi(self, request):
        pi_id = request.query_params.get('proforma_invoice')
        if not pi_id:
            return Response(
                {'error': 'proforma_invoice parameter is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        entries = self.queryset.filter(proforma_invoice_id=pi_id)
        serializer = TransportEntrySerializer(entries, many=True)
        return Response(serializer.data)

    # ── Landed Cost per PI ───────────────────────────────────────────────
    @action(detail=False, methods=['get'])
    def landed_cost_pi(self, request):
        pi_id = request.query_params.get('proforma_invoice')
        if not pi_id:
            return Response({'error': 'proforma_invoice parameter is required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            pi = ProformaInvoice.objects.prefetch_related(
                'items__product', 'transport_entries__cost_items'
            ).get(id=pi_id)
        except ProformaInvoice.DoesNotExist:
            return Response({'error': 'Proforma Invoice not found'}, status=status.HTTP_404_NOT_FOUND)

        total_transport = sum(e.total_cost for e in pi.transport_entries.all())
        items_total = pi.grand_total or Decimal('0')

        items_data = []
        for item in pi.items.all():
            if items_total > 0:
                value_pct = (item.amount / items_total) * Decimal('100')
                allocated = (item.amount / items_total) * total_transport
            else:
                value_pct = Decimal('0')
                allocated = Decimal('0')

            items_data.append({
                'item_id': str(item.id),
                'product_name': item.product.item_name,
                'quantity': float(item.quantity),
                'unit_price': float(item.unit_price),
                'amount': float(item.amount),
                'value_percentage': round(float(value_pct), 2),
                'allocated_transport': round(float(allocated), 2),
                'total_with_transport': round(float(item.amount + allocated), 2),
            })

        return Response({
            'pi_number': pi.pi_number,
            'currency': pi.currency,
            'grand_total': float(pi.grand_total),
            'total_transport_cost': float(total_transport),
            'grand_total_with_transport': float(pi.grand_total + total_transport),
            'items': items_data,
        })

    # ── Transport entries by PO ──────────────────────────────────────────
    @action(detail=False, methods=['get'])
    def by_po(self, request):
        po_id = request.query_params.get('purchase_order')
        if not po_id:
            return Response(
                {'error': 'purchase_order parameter is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        entries = self.queryset.filter(purchase_order_id=po_id)
        serializer = TransportEntrySerializer(entries, many=True)
        return Response(serializer.data)

    # ── Mark delivered ───────────────────────────────────────────────────
    @action(detail=True, methods=['post'])
    def mark_delivered(self, request, pk=None):
        entry = self.get_object()
        if entry.status == 'CANCELLED':
            return Response(
                {'error': 'Cannot mark cancelled entry as delivered'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from django.utils import timezone
        from datetime import date
        entry.status = 'DELIVERED'
        entry.actual_delivery_date = entry.actual_delivery_date or date.today()
        entry.save(update_fields=['status', 'actual_delivery_date'])

        AuditLog.log(request.user, 'UPDATE', entry, {
            'action': 'MARK_DELIVERED',
            'actual_delivery_date': str(entry.actual_delivery_date),
        })
        return Response(TransportEntrySerializer(entry).data)


# ═════════════════════════════════════════════════════════════════════════════
# REPORTS
# ═════════════════════════════════════════════════════════════════════════════

class TransportCostByPOReportView(APIView):
    """Transport cost summary grouped by Purchase Order."""
    permission_classes = [TransportModulePermission]

    def get(self, request):
        entries = TransportEntry.objects.exclude(
            status='CANCELLED'
        ).values(
            'purchase_order__id',
            'purchase_order__po_number',
            'purchase_order__vendor__vendor_name',
            'purchase_order__currency',
            'purchase_order__total_amount',
        ).annotate(
            shipment_count=Count('id'),
            total_transport_cost=Sum('total_cost'),
        ).order_by('-total_transport_cost')

        results = []
        for row in entries:
            po_amount = row['purchase_order__total_amount'] or Decimal('0')
            transport = row['total_transport_cost'] or Decimal('0')
            results.append({
                'po_id': str(row['purchase_order__id']),
                'po_number': row['purchase_order__po_number'],
                'vendor_name': row['purchase_order__vendor__vendor_name'],
                'currency': row['purchase_order__currency'],
                'po_amount': float(po_amount),
                'shipment_count': row['shipment_count'],
                'total_transport_cost': float(transport),
                'grand_total': float(po_amount + transport),
                'transport_percentage': round(float(
                    (transport / po_amount * 100) if po_amount > 0 else 0
                ), 2),
            })

        total_po = sum(r['po_amount'] for r in results)
        total_transport = sum(r['total_transport_cost'] for r in results)

        return Response({
            'total_pos': len(results),
            'total_po_value': total_po,
            'total_transport_cost': total_transport,
            'overall_transport_percentage': round(
                (total_transport / total_po * 100) if total_po > 0 else 0, 2
            ),
            'purchase_orders': results,
        })


class TransportCostByVendorReportView(APIView):
    """Transport cost summary grouped by Vendor."""
    permission_classes = [TransportModulePermission]

    def get(self, request):
        entries = TransportEntry.objects.exclude(
            status='CANCELLED'
        ).values(
            'purchase_order__vendor__id',
            'purchase_order__vendor__vendor_name',
            'purchase_order__vendor__vendor_code',
        ).annotate(
            po_count=Count('purchase_order', distinct=True),
            shipment_count=Count('id'),
            total_transport_cost=Sum('total_cost'),
        ).order_by('-total_transport_cost')

        results = []
        for row in entries:
            results.append({
                'vendor_id': str(row['purchase_order__vendor__id']),
                'vendor_name': row['purchase_order__vendor__vendor_name'],
                'vendor_code': row['purchase_order__vendor__vendor_code'],
                'po_count': row['po_count'],
                'shipment_count': row['shipment_count'],
                'total_transport_cost': float(row['total_transport_cost'] or 0),
            })

        return Response({
            'total_vendors': len(results),
            'total_transport_cost': sum(r['total_transport_cost'] for r in results),
            'vendors': results,
        })


class TransportCostBreakdownReportView(APIView):
    """Transport cost breakdown by cost type across all POs."""
    permission_classes = [TransportModulePermission]

    def get(self, request):
        breakdown = TransportCostItem.objects.filter(
            transport_entry__status__in=['PENDING', 'IN_TRANSIT', 'DELIVERED'],
        ).values('cost_type').annotate(
            total_amount=Sum('amount'),
            entry_count=Count('id'),
        ).order_by('-total_amount')

        cost_type_map = dict(TransportCostItem.COST_TYPE_CHOICES)
        results = []
        grand_total = Decimal('0')
        for row in breakdown:
            amount = row['total_amount'] or Decimal('0')
            grand_total += amount
            results.append({
                'cost_type': row['cost_type'],
                'cost_type_display': cost_type_map.get(row['cost_type'], row['cost_type']),
                'total_amount': float(amount),
                'entry_count': row['entry_count'],
            })

        for r in results:
            r['percentage'] = round(
                (r['total_amount'] / float(grand_total) * 100) if grand_total > 0 else 0, 2
            )

        return Response({
            'grand_total': float(grand_total),
            'breakdown': results,
        })


class LandedCostReportView(APIView):
    """Landed cost report — item-wise across all POs with transport allocation."""
    permission_classes = [TransportModulePermission]

    def get(self, request):
        vendor_id = request.query_params.get('vendor')
        po_status = request.query_params.get('status')

        pos = PurchaseOrder.objects.exclude(
            status='CANCELLED'
        ).select_related('vendor').prefetch_related(
            'items__product', 'transport_entries'
        )
        if vendor_id:
            pos = pos.filter(vendor_id=vendor_id)
        if po_status:
            pos = pos.filter(status=po_status)

        items_report = []
        for po in pos:
            total_transport = sum(e.total_cost for e in po.transport_entries.all())
            items_total = po.items_total or Decimal('0')

            for item in po.items.all():
                if items_total > 0:
                    allocated = (item.amount / items_total) * total_transport
                else:
                    allocated = Decimal('0')

                landed = item.amount + allocated
                landed_rate = landed / item.quantity if item.quantity > 0 else Decimal('0')

                items_report.append({
                    'po_number': po.po_number,
                    'vendor_name': po.vendor.vendor_name,
                    'currency': po.currency,
                    'product_code': item.product.item_code,
                    'product_name': item.product.item_name,
                    'quantity': float(item.quantity),
                    'unit': item.product.unit,
                    'purchase_rate': float(item.rate),
                    'purchase_amount': float(item.amount),
                    'allocated_transport': round(float(allocated), 2),
                    'landed_cost': round(float(landed), 2),
                    'landed_rate_per_unit': round(float(landed_rate), 2),
                    'is_received': item.is_received,
                })

        total_purchase = sum(i['purchase_amount'] for i in items_report)
        total_transport_all = sum(i['allocated_transport'] for i in items_report)
        total_landed = sum(i['landed_cost'] for i in items_report)

        return Response({
            'total_items': len(items_report),
            'total_purchase_value': round(total_purchase, 2),
            'total_transport_cost': round(total_transport_all, 2),
            'total_landed_cost': round(total_landed, 2),
            'items': items_report,
        })


class TransportDashboardView(APIView):
    """Transport module dashboard stats."""
    permission_classes = [TransportModulePermission]

    def get(self, request):
        all_entries = TransportEntry.objects.exclude(status='CANCELLED')

        total_entries = all_entries.count()
        pending = all_entries.filter(status='PENDING').count()
        in_transit = all_entries.filter(status='IN_TRANSIT').count()
        delivered = all_entries.filter(status='DELIVERED').count()

        total_cost = all_entries.aggregate(total=Sum('total_cost'))['total'] or Decimal('0')

        cost_by_type = TransportCostItem.objects.filter(
            transport_entry__status__in=['PENDING', 'IN_TRANSIT', 'DELIVERED'],
        ).values('cost_type').annotate(
            total=Sum('amount')
        ).order_by('-total')

        cost_type_map = dict(TransportCostItem.COST_TYPE_CHOICES)

        recent = TransportEntry.objects.exclude(
            status='CANCELLED'
        ).select_related(
            'purchase_order__vendor', 'created_by'
        ).order_by('-created_at')[:10]

        return Response({
            'summary': {
                'total_entries': total_entries,
                'pending': pending,
                'in_transit': in_transit,
                'delivered': delivered,
                'total_cost': float(total_cost),
            },
            'cost_by_type': [
                {
                    'cost_type': row['cost_type'],
                    'label': cost_type_map.get(row['cost_type'], row['cost_type']),
                    'total': float(row['total'] or 0),
                }
                for row in cost_by_type
            ],
            'recent_entries': TransportEntrySerializer(recent, many=True).data,
        })
