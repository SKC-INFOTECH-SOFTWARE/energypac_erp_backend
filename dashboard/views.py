from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count, Q, F
from decimal import Decimal
from datetime import datetime, timedelta

from inventory.models import Product
from vendors.models import Vendor
from requisitions.models import Requisition, VendorQuotation
from purchase_orders.models import PurchaseOrder


class DashboardStatsView(APIView):
    """
    Complete Dashboard Statistics

    GET /api/dashboard/stats

    Returns:
    - Inventory stats
    - Vendor stats
    - Requisition stats
    - Quotation stats
    - Purchase Order stats
    - Recent activities
    - Alerts & notifications
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Date filters
        today = datetime.now().date()
        last_30_days = today - timedelta(days=30)
        last_7_days = today - timedelta(days=7)

        # ===== INVENTORY STATS =====
        inventory_stats = self._get_inventory_stats()

        # ===== VENDOR STATS =====
        vendor_stats = self._get_vendor_stats()

        # ===== REQUISITION STATS =====
        requisition_stats = self._get_requisition_stats(last_30_days, last_7_days)

        # ===== QUOTATION STATS =====
        quotation_stats = self._get_quotation_stats(last_30_days)

        # ===== PURCHASE ORDER STATS =====
        po_stats = self._get_po_stats(last_30_days, last_7_days)

        # ===== RECENT ACTIVITIES =====
        recent_activities = self._get_recent_activities()

        # ===== ALERTS & NOTIFICATIONS =====
        alerts = self._get_alerts()

        # ===== TOP PRODUCTS =====
        top_products = self._get_top_products()

        # ===== TOP VENDORS =====
        top_vendors = self._get_top_vendors()

        return Response({
            'inventory': inventory_stats,
            'vendors': vendor_stats,
            'requisitions': requisition_stats,
            'quotations': quotation_stats,
            'purchase_orders': po_stats,
            'recent_activities': recent_activities,
            'alerts': alerts,
            'top_products': top_products,
            'top_vendors': top_vendors,
            'generated_at': datetime.now().isoformat()
        })

    def _get_inventory_stats(self):
        """Inventory statistics"""
        total_products = Product.objects.filter(is_active=True).count()

        # Low stock products
        low_stock = Product.objects.filter(
            is_active=True,
            current_stock__lte=F('reorder_level')
        ).count()

        # Out of stock
        out_of_stock = Product.objects.filter(
            is_active=True,
            current_stock=0
        ).count()

        # Total inventory value
        products = Product.objects.filter(is_active=True)
        total_value = sum(
            (p.current_stock * p.rate) for p in products
        )

        return {
            'total_products': total_products,
            'low_stock_items': low_stock,
            'out_of_stock_items': out_of_stock,
            'total_inventory_value': float(total_value),
            'healthy_stock': total_products - low_stock - out_of_stock
        }

    def _get_vendor_stats(self):
        """Vendor statistics"""
        total_vendors = Vendor.objects.filter(is_active=True).count()

        # Vendors with quotations in last 30 days
        active_vendors = Vendor.objects.filter(
            vendorrequisitionassignment__quotations__created_at__gte=datetime.now() - timedelta(days=30)
        ).distinct().count()

        return {
            'total_vendors': total_vendors,
            'active_vendors_last_30_days': active_vendors,
            'inactive_vendors': total_vendors - active_vendors
        }

    def _get_requisition_stats(self, last_30_days, last_7_days):
        """Requisition statistics"""
        total_requisitions = Requisition.objects.count()

        # Pending (not assigned to vendors)
        pending = Requisition.objects.filter(is_assigned=False).count()

        # Assigned
        assigned = Requisition.objects.filter(is_assigned=True).count()

        # Recent requisitions
        last_30 = Requisition.objects.filter(
            requisition_date__gte=last_30_days
        ).count()

        last_7 = Requisition.objects.filter(
            requisition_date__gte=last_7_days
        ).count()

        return {
            'total_requisitions': total_requisitions,
            'pending_requisitions': pending,
            'assigned_requisitions': assigned,
            'last_30_days': last_30,
            'last_7_days': last_7
        }

    def _get_quotation_stats(self, last_30_days):
        """Quotation statistics"""
        total_quotations = VendorQuotation.objects.count()

        # Selected quotations
        selected = VendorQuotation.objects.filter(is_selected=True).count()

        # Pending selection
        pending = total_quotations - selected

        # Recent quotations
        recent = VendorQuotation.objects.filter(
            quotation_date__gte=last_30_days
        ).count()

        # Total quotation value
        total_value = VendorQuotation.objects.aggregate(
            total=Sum('total_amount')
        )['total'] or 0

        return {
            'total_quotations': total_quotations,
            'selected_quotations': selected,
            'pending_selection': pending,
            'recent_quotations_30_days': recent,
            'total_quotation_value': float(total_value)
        }

    def _get_po_stats(self, last_30_days, last_7_days):
        """Purchase Order statistics"""
        total_pos = PurchaseOrder.objects.count()

        # By status
        pending = PurchaseOrder.objects.filter(status='PENDING').count()
        partial = PurchaseOrder.objects.filter(status='PARTIALLY_RECEIVED').count()
        completed = PurchaseOrder.objects.filter(status='COMPLETED').count()

        # Recent POs
        last_30 = PurchaseOrder.objects.filter(
            po_date__gte=last_30_days
        ).count()

        last_7 = PurchaseOrder.objects.filter(
            po_date__gte=last_7_days
        ).count()

        # Total PO value
        total_value = PurchaseOrder.objects.aggregate(
            total=Sum('total_amount')
        )['total'] or 0

        # Pending PO value
        pending_value = PurchaseOrder.objects.filter(
            status__in=['PENDING', 'PARTIALLY_RECEIVED']
        ).aggregate(total=Sum('total_amount'))['total'] or 0

        return {
            'total_purchase_orders': total_pos,
            'pending_pos': pending,
            'partially_received_pos': partial,
            'completed_pos': completed,
            'last_30_days': last_30,
            'last_7_days': last_7,
            'total_po_value': float(total_value),
            'pending_po_value': float(pending_value)
        }

    def _get_recent_activities(self):
        """Recent activities across the system"""
        activities = []

        # Recent requisitions
        recent_reqs = Requisition.objects.order_by('-created_at')[:5]
        for req in recent_reqs:
            activities.append({
                'type': 'requisition',
                'action': 'created',
                'title': f"Requisition {req.requisition_number}",
                'description': f"Created by {req.created_by.get_full_name()}",
                'date': req.created_at.isoformat(),
                'link': f'/requisitions/{req.id}'
            })

        # Recent quotations
        recent_quotes = VendorQuotation.objects.select_related(
            'assignment__vendor'
        ).order_by('-created_at')[:5]
        for quote in recent_quotes:
            activities.append({
                'type': 'quotation',
                'action': 'submitted',
                'title': f"Quotation {quote.quotation_number}",
                'description': f"From {quote.assignment.vendor.vendor_name}",
                'date': quote.created_at.isoformat(),
                'link': f'/quotations/{quote.id}'
            })

        # Recent POs
        recent_pos = PurchaseOrder.objects.select_related(
            'vendor'
        ).order_by('-created_at')[:5]
        for po in recent_pos:
            activities.append({
                'type': 'purchase_order',
                'action': 'created',
                'title': f"PO {po.po_number}",
                'description': f"To {po.vendor.vendor_name} - ₹{po.total_amount}",
                'date': po.created_at.isoformat(),
                'link': f'/purchase-orders/{po.id}'
            })

        # Sort by date
        activities.sort(key=lambda x: x['date'], reverse=True)

        return activities[:10]  # Return top 10

    def _get_alerts(self):
        """System alerts and notifications"""
        alerts = []

        # Low stock alerts
        low_stock_products = Product.objects.filter(
            is_active=True,
            current_stock__lte=F('reorder_level'),
            current_stock__gt=0
        )

        for product in low_stock_products:
            alerts.append({
                'type': 'warning',
                'category': 'inventory',
                'title': 'Low Stock Alert',
                'message': f"{product.item_name} is running low (Stock: {product.current_stock})",
                'action': 'Create requisition',
                'link': f'/products/{product.id}'
            })

        # Out of stock alerts
        out_of_stock = Product.objects.filter(
            is_active=True,
            current_stock=0
        )

        for product in out_of_stock:
            alerts.append({
                'type': 'danger',
                'category': 'inventory',
                'title': 'Out of Stock',
                'message': f"{product.item_name} is out of stock",
                'action': 'Urgent requisition needed',
                'link': f'/products/{product.id}'
            })

        # Pending requisitions
        pending_reqs = Requisition.objects.filter(is_assigned=False).count()
        if pending_reqs > 0:
            alerts.append({
                'type': 'info',
                'category': 'requisition',
                'title': 'Pending Requisitions',
                'message': f"{pending_reqs} requisition(s) waiting for vendor assignment",
                'action': 'Assign vendors',
                'link': '/requisitions?status=pending'
            })

        # Quotations pending selection
        pending_quotes = VendorQuotation.objects.filter(is_selected=False).count()
        if pending_quotes > 0:
            alerts.append({
                'type': 'info',
                'category': 'quotation',
                'title': 'Quotations Pending Selection',
                'message': f"{pending_quotes} quotation(s) waiting for selection",
                'action': 'Review and select',
                'link': '/quotations?status=pending'
            })

        # Pending POs
        pending_pos = PurchaseOrder.objects.filter(
            status__in=['PENDING', 'PARTIALLY_RECEIVED']
        ).count()
        if pending_pos > 0:
            alerts.append({
                'type': 'info',
                'category': 'purchase_order',
                'title': 'Pending Purchase Orders',
                'message': f"{pending_pos} PO(s) waiting for receipt",
                'action': 'Mark as received',
                'link': '/purchase-orders?status=pending'
            })

        return alerts

    def _get_top_products(self):
        """Top products by value"""
        products = Product.objects.filter(is_active=True).annotate(
            stock_value=F('current_stock') * F('rate')
        ).order_by('-stock_value')[:10]

        return [{
            'id': str(p.id),
            'item_code': p.item_code,
            'item_name': p.item_name,
            'current_stock': float(p.current_stock),
            'rate': float(p.rate),
            'stock_value': float(p.current_stock * p.rate)
        } for p in products]

    def _get_top_vendors(self):
        """Top vendors by PO value"""
        from django.db.models import Sum

        vendors = Vendor.objects.filter(
            is_active=True
        ).annotate(
            total_po_value=Sum('purchaseorder__total_amount')
        ).order_by('-total_po_value')[:10]

        return [{
            'id': str(v.id),
            'vendor_code': v.vendor_code,
            'vendor_name': v.vendor_name,
            'total_po_value': float(v.total_po_value or 0),
            'contact_person': v.contact_person,
            'phone': v.phone
        } for v in vendors]
