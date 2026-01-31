
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count, Q, F, Avg
from datetime import datetime, timedelta
from decimal import Decimal

from inventory.models import Product
from vendors.models import Vendor
from requisitions.models import (Requisition, RequisitionItem,
                                VendorRequisitionAssignment,
                                VendorQuotation, VendorQuotationItem)
from purchase_orders.models import PurchaseOrder, PurchaseOrderItem


class ReportsBaseView(APIView):
    """Base class for all reports"""
    permission_classes = [IsAuthenticated]

    def parse_date_range(self, request):
        """Parse date range from request params"""
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        if start_date:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        else:
            # Default: Last 30 days
            start_date = datetime.now().date() - timedelta(days=30)

        if end_date:
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        else:
            end_date = datetime.now().date()

        return start_date, end_date


# ============================================================================
# 1. REQUISITION REPORTS
# ============================================================================

class RequisitionReportView(ReportsBaseView):
    """
    Complete Requisition Report

    GET /api/reports/requisitions?start_date=2026-01-01&end_date=2026-01-31
    GET /api/reports/requisitions?status=pending
    GET /api/reports/requisitions?created_by=user_id
    """

    def get(self, request):
        start_date, end_date = self.parse_date_range(request)

        # Filters
        status = request.query_params.get('status')  # pending, assigned
        created_by = request.query_params.get('created_by')

        # Query
        requisitions = Requisition.objects.filter(
            requisition_date__gte=start_date,
            requisition_date__lte=end_date
        ).select_related('created_by').prefetch_related('items__product')

        if status == 'pending':
            requisitions = requisitions.filter(is_assigned=False)
        elif status == 'assigned':
            requisitions = requisitions.filter(is_assigned=True)

        if created_by:
            requisitions = requisitions.filter(created_by_id=created_by)

        # Summary
        total_requisitions = requisitions.count()
        total_items = RequisitionItem.objects.filter(
            requisition__in=requisitions
        ).count()

        pending_count = requisitions.filter(is_assigned=False).count()
        assigned_count = requisitions.filter(is_assigned=True).count()

        # Detailed data
        report_data = []
        for req in requisitions:
            items_data = []
            for item in req.items.all():
                items_data.append({
                    'product_code': item.product.item_code,
                    'product_name': item.product.item_name,
                    'quantity': float(item.quantity),
                    'unit': item.product.unit,
                    'remarks': item.remarks
                })

            report_data.append({
                'requisition_number': req.requisition_number,
                'requisition_date': req.requisition_date.isoformat(),
                'created_by': req.created_by.get_full_name(),
                'is_assigned': req.is_assigned,
                'status': 'Assigned' if req.is_assigned else 'Pending',
                'total_items': len(items_data),
                'remarks': req.remarks,
                'items': items_data,
                'created_at': req.created_at.isoformat()
            })

        return Response({
            'report_type': 'Requisition Report',
            'date_range': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'summary': {
                'total_requisitions': total_requisitions,
                'total_items': total_items,
                'pending_requisitions': pending_count,
                'assigned_requisitions': assigned_count
            },
            'requisitions': report_data,
            'generated_at': datetime.now().isoformat(),
            'generated_by': request.user.get_full_name()
        })


class RequisitionDetailedReportView(ReportsBaseView):
    """
    Single Requisition Detailed Report

    GET /api/reports/requisitions/{id}/detailed
    """

    def get(self, request, pk):
        try:
            requisition = Requisition.objects.select_related('created_by').get(id=pk)
        except Requisition.DoesNotExist:
            return Response({'error': 'Requisition not found'}, status=404)

        # Items
        items = []
        for item in requisition.items.all():
            items.append({
                'product_code': item.product.item_code,
                'product_name': item.product.item_name,
                'quantity': float(item.quantity),
                'unit': item.product.unit,
                'rate': float(item.product.rate),
                'estimated_value': float(item.quantity * item.product.rate),
                'remarks': item.remarks
            })

        # Vendor assignments
        assignments = []
        for assign in requisition.vendorrequisitionassignment_set.all():
            assignments.append({
                'vendor_name': assign.vendor.vendor_name,
                'vendor_code': assign.vendor.vendor_code,
                'assignment_date': assign.assignment_date.isoformat(),
                'assigned_by': assign.assigned_by.get_full_name()
            })

        # Quotations
        quotations = []
        for assign in requisition.vendorrequisitionassignment_set.all():
            for quote in assign.quotations.all():
                quotations.append({
                    'quotation_number': quote.quotation_number,
                    'vendor_name': assign.vendor.vendor_name,
                    'quotation_date': quote.quotation_date.isoformat(),
                    'total_amount': float(quote.total_amount),
                    'is_selected': quote.is_selected
                })

        # Purchase orders
        pos = []
        for po in requisition.purchaseorder_set.all():
            pos.append({
                'po_number': po.po_number,
                'vendor_name': po.vendor.vendor_name,
                'po_date': po.po_date.isoformat(),
                'total_amount': float(po.total_amount),
                'status': po.status
            })

        return Response({
            'requisition_number': requisition.requisition_number,
            'requisition_date': requisition.requisition_date.isoformat(),
            'created_by': requisition.created_by.get_full_name(),
            'created_at': requisition.created_at.isoformat(),
            'is_assigned': requisition.is_assigned,
            'remarks': requisition.remarks,
            'items': items,
            'total_items': len(items),
            'estimated_total_value': sum(i['estimated_value'] for i in items),
            'vendor_assignments': assignments,
            'quotations_received': quotations,
            'purchase_orders': pos,
            'generated_at': datetime.now().isoformat()
        })


# ============================================================================
# 2. VENDOR REPORTS
# ============================================================================

class VendorPerformanceReportView(ReportsBaseView):
    """
    Vendor Performance Report

    GET /api/reports/vendors/performance?start_date=2026-01-01&end_date=2026-01-31
    GET /api/reports/vendors/performance?vendor=vendor_id
    """

    def get(self, request):
        start_date, end_date = self.parse_date_range(request)
        vendor_id = request.query_params.get('vendor')

        vendors = Vendor.objects.filter(is_active=True)
        if vendor_id:
            vendors = vendors.filter(id=vendor_id)

        report_data = []

        for vendor in vendors:
            # Quotations submitted
            quotations = VendorQuotation.objects.filter(
                assignment__vendor=vendor,
                quotation_date__gte=start_date,
                quotation_date__lte=end_date
            )

            total_quotations = quotations.count()
            selected_quotations = quotations.filter(is_selected=True).count()

            # Purchase orders
            pos = PurchaseOrder.objects.filter(
                vendor=vendor,
                po_date__gte=start_date,
                po_date__lte=end_date
            )

            total_pos = pos.count()
            completed_pos = pos.filter(status='COMPLETED').count()
            total_po_value = pos.aggregate(Sum('total_amount'))['total_amount__sum'] or 0

            # Average quotation value
            avg_quotation = quotations.aggregate(Avg('total_amount'))['total_amount__avg'] or 0

            # Selection rate
            selection_rate = (selected_quotations / total_quotations * 100) if total_quotations > 0 else 0

            # Completion rate
            completion_rate = (completed_pos / total_pos * 100) if total_pos > 0 else 0

            report_data.append({
                'vendor_code': vendor.vendor_code,
                'vendor_name': vendor.vendor_name,
                'contact_person': vendor.contact_person,
                'phone': vendor.phone,
                'email': vendor.email,
                'performance': {
                    'quotations_submitted': total_quotations,
                    'quotations_selected': selected_quotations,
                    'selection_rate': round(selection_rate, 2),
                    'purchase_orders': total_pos,
                    'completed_orders': completed_pos,
                    'completion_rate': round(completion_rate, 2),
                    'total_business_value': float(total_po_value),
                    'average_quotation_value': float(avg_quotation)
                }
            })

        # Sort by total business value
        report_data.sort(key=lambda x: x['performance']['total_business_value'], reverse=True)

        return Response({
            'report_type': 'Vendor Performance Report',
            'date_range': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'total_vendors': len(report_data),
            'vendors': report_data,
            'generated_at': datetime.now().isoformat()
        })


class VendorQuotationComparisonReportView(ReportsBaseView):
    """
    Vendor Quotation Comparison Report

    GET /api/reports/vendors/quotation-comparison?requisition=req_id
    """

    def get(self, request):
        requisition_id = request.query_params.get('requisition')

        if not requisition_id:
            return Response({'error': 'requisition parameter required'}, status=400)

        try:
            requisition = Requisition.objects.get(id=requisition_id)
        except Requisition.DoesNotExist:
            return Response({'error': 'Requisition not found'}, status=404)

        # Get all quotations for this requisition
        assignments = VendorRequisitionAssignment.objects.filter(
            requisition=requisition
        ).select_related('vendor').prefetch_related('quotations__items__product')

        comparison_data = []

        for assign in assignments:
            for quote in assign.quotations.all():
                items = []
                for item in quote.items.all():
                    items.append({
                        'product_code': item.product.item_code,
                        'product_name': item.product.item_name,
                        'quantity': float(item.quantity),
                        'quoted_rate': float(item.quoted_rate),
                        'amount': float(item.amount)
                    })

                comparison_data.append({
                    'vendor_name': assign.vendor.vendor_name,
                    'vendor_code': assign.vendor.vendor_code,
                    'quotation_number': quote.quotation_number,
                    'quotation_date': quote.quotation_date.isoformat(),
                    'total_amount': float(quote.total_amount),
                    'is_selected': quote.is_selected,
                    'items': items
                })

        # Calculate savings if selection made
        selected_quote = next((q for q in comparison_data if q['is_selected']), None)
        if selected_quote:
            all_amounts = [q['total_amount'] for q in comparison_data]
            max_amount = max(all_amounts)
            savings = max_amount - selected_quote['total_amount']
            savings_percentage = (savings / max_amount * 100) if max_amount > 0 else 0
        else:
            savings = 0
            savings_percentage = 0

        return Response({
            'report_type': 'Vendor Quotation Comparison',
            'requisition_number': requisition.requisition_number,
            'requisition_date': requisition.requisition_date.isoformat(),
            'total_vendors': len(comparison_data),
            'quotations': comparison_data,
            'analysis': {
                'lowest_quote': min(comparison_data, key=lambda x: x['total_amount']) if comparison_data else None,
                'highest_quote': max(comparison_data, key=lambda x: x['total_amount']) if comparison_data else None,
                'selected_quote': selected_quote,
                'savings_achieved': float(savings),
                'savings_percentage': round(savings_percentage, 2)
            },
            'generated_at': datetime.now().isoformat()
        })


# ============================================================================
# 3. PURCHASE ORDER REPORTS
# ============================================================================

class PurchaseOrderReportView(ReportsBaseView):
    """
    Purchase Order Report

    GET /api/reports/purchase-orders?start_date=2026-01-01&end_date=2026-01-31
    GET /api/reports/purchase-orders?status=PENDING
    GET /api/reports/purchase-orders?vendor=vendor_id
    """

    def get(self, request):
        start_date, end_date = self.parse_date_range(request)

        # Filters
        status = request.query_params.get('status')
        vendor_id = request.query_params.get('vendor')

        pos = PurchaseOrder.objects.filter(
            po_date__gte=start_date,
            po_date__lte=end_date
        ).select_related('vendor', 'requisition', 'created_by').prefetch_related('items__product')

        if status:
            pos = pos.filter(status=status)

        if vendor_id:
            pos = pos.filter(vendor_id=vendor_id)

        # Summary
        total_pos = pos.count()
        total_value = pos.aggregate(Sum('total_amount'))['total_amount__sum'] or 0

        pending = pos.filter(status='PENDING').count()
        partial = pos.filter(status='PARTIALLY_RECEIVED').count()
        completed = pos.filter(status='COMPLETED').count()

        # Detailed data
        report_data = []
        for po in pos:
            items_data = []
            for item in po.items.all():
                items_data.append({
                    'product_code': item.product.item_code,
                    'product_name': item.product.item_name,
                    'quantity': float(item.quantity),
                    'rate': float(item.rate),
                    'amount': float(item.amount),
                    'is_received': item.is_received
                })

            report_data.append({
                'po_number': po.po_number,
                'po_date': po.po_date.isoformat(),
                'vendor_name': po.vendor.vendor_name,
                'vendor_code': po.vendor.vendor_code,
                'requisition_number': po.requisition.requisition_number,
                'total_amount': float(po.total_amount),
                'status': po.status,
                'items': items_data,
                'total_items': len(items_data),
                'created_by': po.created_by.get_full_name(),
                'created_at': po.created_at.isoformat()
            })

        return Response({
            'report_type': 'Purchase Order Report',
            'date_range': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'summary': {
                'total_purchase_orders': total_pos,
                'total_value': float(total_value),
                'pending_pos': pending,
                'partially_received_pos': partial,
                'completed_pos': completed
            },
            'purchase_orders': report_data,
            'generated_at': datetime.now().isoformat(),
            'generated_by': request.user.get_full_name()
        })


# ============================================================================
# 4. INVENTORY REPORTS
# ============================================================================

class InventoryStockReportView(ReportsBaseView):
    """
    Inventory Stock Report

    GET /api/reports/inventory/stock
    GET /api/reports/inventory/stock?status=low_stock
    GET /api/reports/inventory/stock?status=out_of_stock
    """

    def get(self, request):
        status_filter = request.query_params.get('status')

        products = Product.objects.filter(is_active=True)

        if status_filter == 'low_stock':
            products = products.filter(current_stock__lte=F('reorder_level'), current_stock__gt=0)
        elif status_filter == 'out_of_stock':
            products = products.filter(current_stock=0)
        elif status_filter == 'healthy':
            products = products.filter(current_stock__gt=F('reorder_level'))

        report_data = []
        total_value = 0

        for product in products:
            stock_value = product.current_stock * product.rate
            total_value += stock_value

            # Stock status
            if product.current_stock == 0:
                stock_status = 'Out of Stock'
            elif product.current_stock <= product.reorder_level:
                stock_status = 'Low Stock'
            else:
                stock_status = 'Healthy'

            report_data.append({
                'item_code': product.item_code,
                'item_name': product.item_name,
                'current_stock': float(product.current_stock),
                'reorder_level': float(product.reorder_level),
                'unit': product.unit,
                'rate': float(product.rate),
                'stock_value': float(stock_value),
                'stock_status': stock_status,
                'hsn_code': product.hsn_code
            })

        # Summary
        total_products = len(report_data)
        low_stock = sum(1 for p in report_data if p['stock_status'] == 'Low Stock')
        out_of_stock = sum(1 for p in report_data if p['stock_status'] == 'Out of Stock')
        healthy = sum(1 for p in report_data if p['stock_status'] == 'Healthy')

        return Response({
            'report_type': 'Inventory Stock Report',
            'summary': {
                'total_products': total_products,
                'total_inventory_value': float(total_value),
                'healthy_stock': healthy,
                'low_stock': low_stock,
                'out_of_stock': out_of_stock
            },
            'products': report_data,
            'generated_at': datetime.now().isoformat()
        })


class InventoryMovementReportView(ReportsBaseView):
    """
    Inventory Movement Report (Stock In/Out via POs)

    GET /api/reports/inventory/movement?start_date=2026-01-01&end_date=2026-01-31
    GET /api/reports/inventory/movement?product=product_id
    """

    def get(self, request):
        start_date, end_date = self.parse_date_range(request)
        product_id = request.query_params.get('product')

        # Get all received PO items in date range
        po_items = PurchaseOrderItem.objects.filter(
            is_received=True,
            po__po_date__gte=start_date,
            po__po_date__lte=end_date
        ).select_related('product', 'po__vendor')

        if product_id:
            po_items = po_items.filter(product_id=product_id)

        movements = []
        total_quantity_in = 0
        total_value_in = 0

        for item in po_items:
            quantity = float(item.quantity)
            value = float(item.amount)
            total_quantity_in += quantity
            total_value_in += value

            movements.append({
                'date': item.po.po_date.isoformat(),
                'type': 'Stock In',
                'po_number': item.po.po_number,
                'product_code': item.product.item_code,
                'product_name': item.product.item_name,
                'quantity': quantity,
                'unit': item.product.unit,
                'rate': float(item.rate),
                'value': value,
                'vendor': item.po.vendor.vendor_name
            })

        return Response({
            'report_type': 'Inventory Movement Report',
            'date_range': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'summary': {
                'total_movements': len(movements),
                'total_quantity_received': total_quantity_in,
                'total_value_received': total_value_in
            },
            'movements': movements,
            'generated_at': datetime.now().isoformat()
        })


# ============================================================================
# 5. FINANCIAL/SPENDING REPORTS
# ============================================================================

class SpendingAnalysisReportView(ReportsBaseView):
    """
    Spending Analysis Report

    GET /api/reports/financial/spending?start_date=2026-01-01&end_date=2026-01-31
    GET /api/reports/financial/spending?group_by=vendor
    GET /api/reports/financial/spending?group_by=month
    """

    def get(self, request):
        start_date, end_date = self.parse_date_range(request)
        group_by = request.query_params.get('group_by', 'vendor')  # vendor, month, category

        pos = PurchaseOrder.objects.filter(
            po_date__gte=start_date,
            po_date__lte=end_date
        ).select_related('vendor')

        total_spending = pos.aggregate(Sum('total_amount'))['total_amount__sum'] or 0

        if group_by == 'vendor':
            # Group by vendor
            vendor_spending = pos.values(
                'vendor__vendor_name', 'vendor__vendor_code'
            ).annotate(
                total_spent=Sum('total_amount'),
                po_count=Count('id')
            ).order_by('-total_spent')

            breakdown = [{
                'vendor_name': item['vendor__vendor_name'],
                'vendor_code': item['vendor__vendor_code'],
                'total_spent': float(item['total_spent']),
                'purchase_orders': item['po_count'],
                'percentage': round(float(item['total_spent']) / float(total_spending) * 100, 2) if total_spending > 0 else 0
            } for item in vendor_spending]

        elif group_by == 'month':
            # Group by month
            from django.db.models.functions import TruncMonth
            monthly_spending = pos.annotate(
                month=TruncMonth('po_date')
            ).values('month').annotate(
                total_spent=Sum('total_amount'),
                po_count=Count('id')
            ).order_by('month')

            breakdown = [{
                'month': item['month'].strftime('%B %Y'),
                'total_spent': float(item['total_spent']),
                'purchase_orders': item['po_count']
            } for item in monthly_spending]

        else:
            breakdown = []

        return Response({
            'report_type': 'Spending Analysis Report',
            'date_range': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'summary': {
                'total_spending': float(total_spending),
                'total_purchase_orders': pos.count(),
                'average_po_value': float(total_spending / pos.count()) if pos.count() > 0 else 0
            },
            'breakdown': breakdown,
            'grouped_by': group_by,
            'generated_at': datetime.now().isoformat()
        })
