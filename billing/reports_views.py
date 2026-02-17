"""
Billing & Work Order Reports
Complete reporting and statistics for billing and work order management
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count, Q, F, Avg, Max, Min
from django.db.models.functions import TruncMonth, TruncWeek, TruncDate
from datetime import datetime, timedelta
from decimal import Decimal

from billing.models import Bill, BillItem
from work_orders.models import WorkOrder, WorkOrderItem
from sales.models import SalesQuotation


class BillingReportsBaseView(APIView):
    """Base class for all billing reports"""
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
# 1. BILLING REPORTS
# ============================================================================

class BillReportView(BillingReportsBaseView):
    """
    Complete Bill Report

    GET /api/reports/billing/bills?start_date=2026-01-01&end_date=2026-02-28
    GET /api/reports/billing/bills?status=GENERATED
    GET /api/reports/billing/bills?work_order=wo_id
    """

    def get(self, request):
        start_date, end_date = self.parse_date_range(request)

        # Filters
        status_filter = request.query_params.get('status')
        work_order_id = request.query_params.get('work_order')

        # Query
        bills = Bill.objects.filter(
            bill_date__gte=start_date,
            bill_date__lte=end_date
        ).select_related('work_order', 'created_by').prefetch_related('items')

        if status_filter:
            bills = bills.filter(status=status_filter)

        if work_order_id:
            bills = bills.filter(work_order_id=work_order_id)

        # Summary statistics
        total_bills = bills.count()
        total_amount = bills.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        total_advance_deducted = bills.aggregate(Sum('advance_deducted'))['advance_deducted__sum'] or 0
        total_net_payable = bills.aggregate(Sum('net_payable'))['net_payable__sum'] or 0
        total_paid = bills.aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
        total_balance = bills.aggregate(Sum('balance'))['balance__sum'] or 0

        # Status breakdown
        generated_count = bills.filter(status='GENERATED').count()
        paid_count = bills.filter(status='PAID').count()
        cancelled_count = bills.filter(status='CANCELLED').count()

        # Tax statistics
        total_cgst = bills.aggregate(Sum('cgst_amount'))['cgst_amount__sum'] or 0
        total_sgst = bills.aggregate(Sum('sgst_amount'))['sgst_amount__sum'] or 0
        total_igst = bills.aggregate(Sum('igst_amount'))['igst_amount__sum'] or 0

        # Detailed data
        report_data = []
        for bill in bills:
            items_count = bill.items.count()

            report_data.append({
                'bill_number': bill.bill_number,
                'bill_date': bill.bill_date.isoformat(),
                'wo_number': bill.work_order.wo_number,
                'client_name': bill.client_name,
                'contact_person': bill.contact_person,
                'phone': bill.phone,
                'total_items': items_count,
                'subtotal': float(bill.subtotal),
                'tax_summary': {
                    'cgst': float(bill.cgst_amount),
                    'sgst': float(bill.sgst_amount),
                    'igst': float(bill.igst_amount),
                    'total_tax': float(bill.cgst_amount + bill.sgst_amount + bill.igst_amount)
                },
                'total_amount': float(bill.total_amount),
                'advance_deducted': float(bill.advance_deducted),
                'net_payable': float(bill.net_payable),
                'amount_paid': float(bill.amount_paid),
                'balance': float(bill.balance),
                'status': bill.status,
                'created_by': bill.created_by.get_full_name(),
                'created_at': bill.created_at.isoformat()
            })

        return Response({
            'report_type': 'Bill Report',
            'date_range': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'summary': {
                'total_bills': total_bills,
                'total_amount': float(total_amount),
                'total_advance_deducted': float(total_advance_deducted),
                'total_net_payable': float(total_net_payable),
                'total_paid': float(total_paid),
                'total_outstanding': float(total_balance),
                'generated_bills': generated_count,
                'paid_bills': paid_count,
                'cancelled_bills': cancelled_count,
                'tax_collected': {
                    'cgst': float(total_cgst),
                    'sgst': float(total_sgst),
                    'igst': float(total_igst),
                    'total': float(total_cgst + total_sgst + total_igst)
                }
            },
            'bills': report_data,
            'generated_at': datetime.now().isoformat(),
            'generated_by': request.user.get_full_name()
        })


class BillDetailedReportView(BillingReportsBaseView):
    """
    Single Bill Detailed Report

    GET /api/reports/billing/bills/{id}/detailed
    """

    def get(self, request, pk):
        try:
            bill = Bill.objects.select_related('work_order', 'created_by').get(id=pk)
        except Bill.DoesNotExist:
            return Response({'error': 'Bill not found'}, status=404)

        # Items
        items = []
        for item in bill.items.all():
            items.append({
                'item_code': item.item_code,
                'item_name': item.item_name,
                'description': item.description,
                'hsn_code': item.hsn_code,
                'unit': item.unit,
                'ordered_quantity': float(item.ordered_quantity),
                'previously_delivered': float(item.previously_delivered_quantity),
                'delivered_quantity': float(item.delivered_quantity),
                'pending_quantity': float(item.pending_quantity),
                'rate': float(item.rate),
                'amount': float(item.amount),
                'remarks': item.remarks
            })

        return Response({
            'bill_number': bill.bill_number,
            'bill_date': bill.bill_date.isoformat(),
            'work_order': {
                'wo_number': bill.work_order.wo_number,
                'wo_date': bill.work_order.wo_date.isoformat(),
                'status': bill.work_order.status
            },
            'client_details': {
                'name': bill.client_name,
                'contact_person': bill.contact_person,
                'phone': bill.phone,
                'email': bill.email,
                'address': bill.address
            },
            'items': items,
            'total_items': len(items),
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
                'total_tax': float(bill.cgst_amount + bill.sgst_amount + bill.igst_amount),
                'total_amount': float(bill.total_amount),
                'advance_deducted': float(bill.advance_deducted),
                'net_payable': float(bill.net_payable),
                'amount_paid': float(bill.amount_paid),
                'balance': float(bill.balance)
            },
            'status': bill.status,
            'remarks': bill.remarks,
            'created_by': bill.created_by.get_full_name(),
            'created_at': bill.created_at.isoformat(),
            'generated_at': datetime.now().isoformat()
        })


class BillingAnalyticsView(BillingReportsBaseView):
    """
    Billing Analytics & Trends

    GET /api/reports/billing/analytics?start_date=2026-01-01&end_date=2026-02-28
    GET /api/reports/billing/analytics?group_by=month
    """

    def get(self, request):
        start_date, end_date = self.parse_date_range(request)
        group_by = request.query_params.get('group_by', 'month')

        bills = Bill.objects.filter(
            bill_date__gte=start_date,
            bill_date__lte=end_date
        ).exclude(status='CANCELLED')

        # Overall statistics
        total_bills = bills.count()
        total_revenue = bills.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        total_received = bills.aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
        total_outstanding = bills.aggregate(Sum('balance'))['balance__sum'] or 0
        avg_bill_value = bills.aggregate(Avg('total_amount'))['total_amount__avg'] or 0

        # Time-based trends
        if group_by == 'month':
            time_data = bills.annotate(
                period=TruncMonth('bill_date')
            ).values('period').annotate(
                bills_count=Count('id'),
                total_revenue=Sum('total_amount'),
                total_received=Sum('amount_paid'),
                total_outstanding=Sum('balance')
            ).order_by('period')
        elif group_by == 'week':
            time_data = bills.annotate(
                period=TruncWeek('bill_date')
            ).values('period').annotate(
                bills_count=Count('id'),
                total_revenue=Sum('total_amount'),
                total_received=Sum('amount_paid'),
                total_outstanding=Sum('balance')
            ).order_by('period')
        else:  # day
            time_data = bills.annotate(
                period=TruncDate('bill_date')
            ).values('period').annotate(
                bills_count=Count('id'),
                total_revenue=Sum('total_amount'),
                total_received=Sum('amount_paid'),
                total_outstanding=Sum('balance')
            ).order_by('period')

        # Top clients by revenue
        top_clients = bills.values('client_name').annotate(
            total_revenue=Sum('total_amount'),
            total_bills=Count('id'),
            total_paid=Sum('amount_paid'),
            total_outstanding=Sum('balance')
        ).order_by('-total_revenue')[:10]

        # Payment collection rate
        collection_rate = (float(total_received) / float(total_revenue) * 100) if total_revenue > 0 else 0

        # Average time to payment (for paid bills)
        paid_bills = bills.filter(status='PAID')
        avg_payment_days = 0
        if paid_bills.exists():
            payment_times = []
            for bill in paid_bills:
                # Estimate using updated_at as payment date
                days_diff = (bill.updated_at.date() - bill.bill_date).days
                payment_times.append(days_diff)
            avg_payment_days = sum(payment_times) / len(payment_times) if payment_times else 0

        return Response({
            'report_type': 'Billing Analytics',
            'date_range': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'overall_statistics': {
                'total_bills': total_bills,
                'total_revenue': float(total_revenue),
                'total_received': float(total_received),
                'total_outstanding': float(total_outstanding),
                'average_bill_value': float(avg_bill_value),
                'collection_rate': round(collection_rate, 2),
                'average_payment_days': round(avg_payment_days, 1)
            },
            'time_trends': [{
                'period': item['period'].strftime('%Y-%m-%d'),
                'bills_count': item['bills_count'],
                'total_revenue': float(item['total_revenue']),
                'total_received': float(item['total_received']),
                'total_outstanding': float(item['total_outstanding'])
            } for item in time_data],
            'top_clients': [{
                'client_name': item['client_name'],
                'total_revenue': float(item['total_revenue']),
                'total_bills': item['total_bills'],
                'total_paid': float(item['total_paid']),
                'total_outstanding': float(item['total_outstanding'])
            } for item in top_clients],
            'generated_at': datetime.now().isoformat(),
            'grouped_by': group_by
        })


class OutstandingPaymentsReportView(BillingReportsBaseView):
    """
    Outstanding Payments Report

    GET /api/reports/billing/outstanding
    GET /api/reports/billing/outstanding?aging=true
    """

    def get(self, request):
        aging = request.query_params.get('aging', 'false').lower() == 'true'

        # Get all bills with outstanding balance
        outstanding_bills = Bill.objects.filter(
            balance__gt=0
        ).exclude(status='CANCELLED').select_related('work_order', 'created_by')

        total_outstanding = outstanding_bills.aggregate(Sum('balance'))['balance__sum'] or 0
        total_bills = outstanding_bills.count()

        # Aging analysis (if requested)
        aging_data = {}
        if aging:
            today = datetime.now().date()

            # 0-30 days
            range_0_30 = outstanding_bills.filter(
                bill_date__gte=today - timedelta(days=30)
            )
            aging_data['0_30_days'] = {
                'count': range_0_30.count(),
                'amount': float(range_0_30.aggregate(Sum('balance'))['balance__sum'] or 0)
            }

            # 31-60 days
            range_31_60 = outstanding_bills.filter(
                bill_date__gte=today - timedelta(days=60),
                bill_date__lt=today - timedelta(days=30)
            )
            aging_data['31_60_days'] = {
                'count': range_31_60.count(),
                'amount': float(range_31_60.aggregate(Sum('balance'))['balance__sum'] or 0)
            }

            # 61-90 days
            range_61_90 = outstanding_bills.filter(
                bill_date__gte=today - timedelta(days=90),
                bill_date__lt=today - timedelta(days=60)
            )
            aging_data['61_90_days'] = {
                'count': range_61_90.count(),
                'amount': float(range_61_90.aggregate(Sum('balance'))['balance__sum'] or 0)
            }

            # 90+ days
            range_90_plus = outstanding_bills.filter(
                bill_date__lt=today - timedelta(days=90)
            )
            aging_data['90_plus_days'] = {
                'count': range_90_plus.count(),
                'amount': float(range_90_plus.aggregate(Sum('balance'))['balance__sum'] or 0)
            }

        # Detailed list
        bills_data = []
        for bill in outstanding_bills:
            days_outstanding = (datetime.now().date() - bill.bill_date).days

            bills_data.append({
                'bill_number': bill.bill_number,
                'bill_date': bill.bill_date.isoformat(),
                'wo_number': bill.work_order.wo_number,
                'client_name': bill.client_name,
                'contact_person': bill.contact_person,
                'phone': bill.phone,
                'email': bill.email,
                'total_amount': float(bill.total_amount),
                'amount_paid': float(bill.amount_paid),
                'balance': float(bill.balance),
                'days_outstanding': days_outstanding,
                'status': bill.status
            })

        response_data = {
            'report_type': 'Outstanding Payments Report',
            'summary': {
                'total_outstanding_bills': total_bills,
                'total_outstanding_amount': float(total_outstanding)
            },
            'bills': bills_data,
            'generated_at': datetime.now().isoformat()
        }

        if aging:
            response_data['aging_analysis'] = aging_data

        return Response(response_data)


# ============================================================================
# 2. WORK ORDER REPORTS
# ============================================================================

class WorkOrderReportView(BillingReportsBaseView):
    """
    Complete Work Order Report

    GET /api/reports/work-orders?start_date=2026-01-01&end_date=2026-02-28
    GET /api/reports/work-orders?status=ACTIVE
    """

    def get(self, request):
        start_date, end_date = self.parse_date_range(request)

        # Filters
        status_filter = request.query_params.get('status')

        # Query
        work_orders = WorkOrder.objects.filter(
            wo_date__gte=start_date,
            wo_date__lte=end_date
        ).select_related('sales_quotation', 'created_by').prefetch_related('items')

        if status_filter:
            work_orders = work_orders.filter(status=status_filter)

        # Summary statistics
        total_wos = work_orders.count()
        total_value = work_orders.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        total_advance = work_orders.aggregate(Sum('advance_amount'))['advance_amount__sum'] or 0
        total_delivered = work_orders.aggregate(Sum('total_delivered_value'))['total_delivered_value__sum'] or 0

        # Status breakdown
        active_count = work_orders.filter(status='ACTIVE').count()
        partial_count = work_orders.filter(status='PARTIALLY_DELIVERED').count()
        completed_count = work_orders.filter(status='COMPLETED').count()
        cancelled_count = work_orders.filter(status='CANCELLED').count()

        # Detailed data
        report_data = []
        for wo in work_orders:
            items = wo.items.all()
            total_items = items.count()

            # Calculate completion percentage
            total_ordered = sum(item.ordered_quantity for item in items)
            total_delivered_qty = sum(item.delivered_quantity for item in items)
            completion_pct = (total_delivered_qty / total_ordered * 100) if total_ordered > 0 else 0

            report_data.append({
                'wo_number': wo.wo_number,
                'wo_date': wo.wo_date.isoformat(),
                'quotation_number': wo.sales_quotation.quotation_number,
                'client_name': wo.client_name,
                'contact_person': wo.contact_person,
                'phone': wo.phone,
                'total_items': total_items,
                'total_amount': float(wo.total_amount),
                'advance_amount': float(wo.advance_amount),
                'advance_remaining': float(wo.advance_remaining),
                'total_delivered_value': float(wo.total_delivered_value),
                'completion_percentage': round(completion_pct, 2),
                'status': wo.status,
                'created_by': wo.created_by.get_full_name(),
                'created_at': wo.created_at.isoformat()
            })

        return Response({
            'report_type': 'Work Order Report',
            'date_range': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'summary': {
                'total_work_orders': total_wos,
                'total_value': float(total_value),
                'total_advance_received': float(total_advance),
                'total_delivered_value': float(total_delivered),
                'active_wos': active_count,
                'partially_delivered_wos': partial_count,
                'completed_wos': completed_count,
                'cancelled_wos': cancelled_count
            },
            'work_orders': report_data,
            'generated_at': datetime.now().isoformat(),
            'generated_by': request.user.get_full_name()
        })


class WorkOrderDetailedReportView(BillingReportsBaseView):
    """
    Single Work Order Detailed Report

    GET /api/reports/work-orders/{id}/detailed
    """

    def get(self, request, pk):
        try:
            wo = WorkOrder.objects.select_related(
                'sales_quotation__client_query', 'created_by'
            ).prefetch_related('items', 'bills').get(id=pk)
        except WorkOrder.DoesNotExist:
            return Response({'error': 'Work order not found'}, status=404)

        # Items with delivery status
        items = []
        for item in wo.items.all():
            stock_status = item.get_stock_status()

            items.append({
                'item_code': item.item_code,
                'item_name': item.item_name,
                'description': item.description,
                'hsn_code': item.hsn_code,
                'unit': item.unit,
                'ordered_quantity': float(item.ordered_quantity),
                'delivered_quantity': float(item.delivered_quantity),
                'pending_quantity': float(item.pending_quantity),
                'rate': float(item.rate),
                'amount': float(item.amount),
                'stock_status': stock_status,
                'remarks': item.remarks
            })

        # Bills generated
        bills = []
        for bill in wo.bills.all():
            bills.append({
                'bill_number': bill.bill_number,
                'bill_date': bill.bill_date.isoformat(),
                'total_amount': float(bill.total_amount),
                'advance_deducted': float(bill.advance_deducted),
                'net_payable': float(bill.net_payable),
                'amount_paid': float(bill.amount_paid),
                'balance': float(bill.balance),
                'status': bill.status
            })

        # Calculate completion
        total_ordered = sum(item.ordered_quantity for item in wo.items.all())
        total_delivered = sum(item.delivered_quantity for item in wo.items.all())
        completion_pct = (total_delivered / total_ordered * 100) if total_ordered > 0 else 0

        return Response({
            'wo_number': wo.wo_number,
            'wo_date': wo.wo_date.isoformat(),
            'sales_quotation': {
                'quotation_number': wo.sales_quotation.quotation_number,
                'quotation_date': wo.sales_quotation.quotation_date.isoformat(),
                'client_query_number': wo.sales_quotation.client_query.query_number
            },
            'client_details': {
                'name': wo.client_name,
                'contact_person': wo.contact_person,
                'phone': wo.phone,
                'email': wo.email,
                'address': wo.address
            },
            'items': items,
            'total_items': len(items),
            'financial': {
                'subtotal': float(wo.subtotal),
                'cgst_amount': float(wo.cgst_amount),
                'sgst_amount': float(wo.sgst_amount),
                'igst_amount': float(wo.igst_amount),
                'total_amount': float(wo.total_amount),
                'advance_amount': float(wo.advance_amount),
                'advance_deducted': float(wo.advance_deducted),
                'advance_remaining': float(wo.advance_remaining),
                'total_delivered_value': float(wo.total_delivered_value)
            },
            'bills': bills,
            'total_bills': len(bills),
            'delivery_progress': {
                'completion_percentage': round(completion_pct, 2),
                'total_ordered': float(total_ordered),
                'total_delivered': float(total_delivered),
                'total_pending': float(total_ordered - total_delivered)
            },
            'status': wo.status,
            'remarks': wo.remarks,
            'created_by': wo.created_by.get_full_name(),
            'created_at': wo.created_at.isoformat(),
            'generated_at': datetime.now().isoformat()
        })


class WorkOrderDeliveryAnalysisView(BillingReportsBaseView):
    """
    Work Order Delivery Analysis

    GET /api/reports/work-orders/delivery-analysis?start_date=2026-01-01&end_date=2026-02-28
    """

    def get(self, request):
        start_date, end_date = self.parse_date_range(request)

        work_orders = WorkOrder.objects.filter(
            wo_date__gte=start_date,
            wo_date__lte=end_date
        ).prefetch_related('items')

        # Overall delivery statistics
        total_wos = work_orders.count()
        on_time_deliveries = 0
        delayed_deliveries = 0

        # Item-level statistics
        all_items = WorkOrderItem.objects.filter(work_order__in=work_orders)
        total_items = all_items.count()
        fully_delivered_items = all_items.filter(pending_quantity=0).count()
        partially_delivered_items = all_items.filter(
            delivered_quantity__gt=0,
            pending_quantity__gt=0
        ).count()
        pending_items = all_items.filter(delivered_quantity=0).count()

        # Stock availability analysis
        in_stock_items = all_items.filter(
            stock_available=True,
            pending_quantity__gt=0
        ).count()

        out_of_stock_items = all_items.filter(
            stock_available=False,
            pending_quantity__gt=0
        ).count()

        # Work order delivery status
        wo_delivery_status = []
        for wo in work_orders:
            items = wo.items.all()
            total_ordered = sum(item.ordered_quantity for item in items)
            total_delivered = sum(item.delivered_quantity for item in items)
            completion_pct = (total_delivered / total_ordered * 100) if total_ordered > 0 else 0

            wo_delivery_status.append({
                'wo_number': wo.wo_number,
                'client_name': wo.client_name,
                'total_items': items.count(),
                'fully_delivered': items.filter(pending_quantity=0).count(),
                'partially_delivered': items.filter(
                    delivered_quantity__gt=0,
                    pending_quantity__gt=0
                ).count(),
                'pending': items.filter(delivered_quantity=0).count(),
                'completion_percentage': round(completion_pct, 2),
                'status': wo.status
            })

        return Response({
            'report_type': 'Work Order Delivery Analysis',
            'date_range': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'overall_summary': {
                'total_work_orders': total_wos,
                'completed_wos': work_orders.filter(status='COMPLETED').count(),
                'partially_delivered_wos': work_orders.filter(status='PARTIALLY_DELIVERED').count(),
                'pending_wos': work_orders.filter(status='ACTIVE').count()
            },
            'item_summary': {
                'total_items': total_items,
                'fully_delivered_items': fully_delivered_items,
                'partially_delivered_items': partially_delivered_items,
                'pending_items': pending_items,
                'delivery_rate': round((fully_delivered_items / total_items * 100) if total_items > 0 else 0, 2)
            },
            'stock_analysis': {
                'in_stock_pending_items': in_stock_items,
                'out_of_stock_pending_items': out_of_stock_items
            },
            'work_order_details': wo_delivery_status,
            'generated_at': datetime.now().isoformat()
        })


# ============================================================================
# 3. DASHBOARD STATISTICS
# ============================================================================

class BillingDashboardStatsView(APIView):
    """
    Billing & Work Order Dashboard Statistics

    GET /api/dashboard/billing/stats
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = datetime.now().date()
        last_7_days = today - timedelta(days=7)
        last_30_days = today - timedelta(days=30)
        this_month_start = today.replace(day=1)

        # Work Order Stats
        total_wos = WorkOrder.objects.count()
        active_wos = WorkOrder.objects.filter(status='ACTIVE').count()
        partial_wos = WorkOrder.objects.filter(status='PARTIALLY_DELIVERED').count()
        completed_wos = WorkOrder.objects.filter(status='COMPLETED').count()

        wos_this_month = WorkOrder.objects.filter(
            wo_date__gte=this_month_start
        ).count()

        total_wo_value = WorkOrder.objects.aggregate(
            Sum('total_amount')
        )['total_amount__sum'] or 0

        # Bill Stats
        total_bills = Bill.objects.count()
        generated_bills = Bill.objects.filter(status='GENERATED').count()
        paid_bills = Bill.objects.filter(status='PAID').count()

        bills_this_month = Bill.objects.filter(
            bill_date__gte=this_month_start
        ).count()

        total_billed = Bill.objects.exclude(status='CANCELLED').aggregate(
            Sum('total_amount')
        )['total_amount__sum'] or 0

        total_received = Bill.objects.exclude(status='CANCELLED').aggregate(
            Sum('amount_paid')
        )['amount_paid__sum'] or 0

        total_outstanding = Bill.objects.exclude(status='CANCELLED').aggregate(
            Sum('balance')
        )['balance__sum'] or 0

        # Recent activities
        recent_wos = WorkOrder.objects.select_related('created_by').order_by('-created_at')[:5]
        recent_bills = Bill.objects.select_related('created_by', 'work_order').order_by('-created_at')[:5]

        activities = []

        for wo in recent_wos:
            activities.append({
                'type': 'work_order',
                'action': 'created',
                'title': f"Work Order {wo.wo_number}",
                'description': f"For {wo.client_name} - ₹{wo.total_amount}",
                'date': wo.created_at.isoformat(),
                'link': f'/work-orders/{wo.id}'
            })

        for bill in recent_bills:
            activities.append({
                'type': 'bill',
                'action': 'generated',
                'title': f"Bill {bill.bill_number}",
                'description': f"WO {bill.work_order.wo_number} - ₹{bill.total_amount}",
                'date': bill.created_at.isoformat(),
                'link': f'/bills/{bill.id}'
            })

        activities.sort(key=lambda x: x['date'], reverse=True)

        # Alerts
        alerts = []

        # Pending deliveries
        pending_delivery_wos = WorkOrder.objects.filter(
            status__in=['ACTIVE', 'PARTIALLY_DELIVERED']
        ).count()
        if pending_delivery_wos > 0:
            alerts.append({
                'type': 'warning',
                'category': 'work_order',
                'title': 'Pending Deliveries',
                'message': f"{pending_delivery_wos} work order(s) have pending deliveries",
                'action': 'Process deliveries',
                'link': '/work-orders?status=active'
            })

        # Outstanding payments
        outstanding_bills_count = Bill.objects.filter(
            balance__gt=0
        ).exclude(status='CANCELLED').count()
        if outstanding_bills_count > 0:
            alerts.append({
                'type': 'danger',
                'category': 'billing',
                'title': 'Outstanding Payments',
                'message': f"{outstanding_bills_count} bill(s) with pending payment - ₹{total_outstanding}",
                'action': 'Follow up',
                'link': '/bills?status=pending'
            })

        # Low stock items affecting work orders
        from inventory.models import Product
        low_stock_count = Product.objects.filter(
            current_stock__lte=F('reorder_level'),
            is_active=True
        ).count()
        if low_stock_count > 0:
            alerts.append({
                'type': 'warning',
                'category': 'inventory',
                'title': 'Low Stock Alert',
                'message': f"{low_stock_count} product(s) running low - may affect deliveries",
                'action': 'Check inventory',
                'link': '/inventory?status=low_stock'
            })

        return Response({
            'work_orders': {
                'total': total_wos,
                'active': active_wos,
                'partially_delivered': partial_wos,
                'completed': completed_wos,
                'this_month': wos_this_month,
                'total_value': float(total_wo_value)
            },
            'bills': {
                'total': total_bills,
                'generated': generated_bills,
                'paid': paid_bills,
                'this_month': bills_this_month,
                'total_billed': float(total_billed),
                'total_received': float(total_received),
                'total_outstanding': float(total_outstanding),
                'collection_rate': round((float(total_received) / float(total_billed) * 100) if total_billed > 0 else 0, 2)
            },
            'recent_activities': activities[:10],
            'alerts': alerts,
            'generated_at': datetime.now().isoformat()
        })
"""
Billing & Work Order Reports
Complete reporting and statistics for billing and work order management
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count, Q, F, Avg, Max, Min
from django.db.models.functions import TruncMonth, TruncWeek, TruncDate
from datetime import datetime, timedelta
from decimal import Decimal

from billing.models import Bill, BillItem
from work_orders.models import WorkOrder, WorkOrderItem
from sales.models import SalesQuotation


class BillingReportsBaseView(APIView):
    """Base class for all billing reports"""
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
# 1. BILLING REPORTS
# ============================================================================

class BillReportView(BillingReportsBaseView):
    """
    Complete Bill Report

    GET /api/reports/billing/bills?start_date=2026-01-01&end_date=2026-02-28
    GET /api/reports/billing/bills?status=GENERATED
    GET /api/reports/billing/bills?work_order=wo_id
    """

    def get(self, request):
        start_date, end_date = self.parse_date_range(request)

        # Filters
        status_filter = request.query_params.get('status')
        work_order_id = request.query_params.get('work_order')

        # Query
        bills = Bill.objects.filter(
            bill_date__gte=start_date,
            bill_date__lte=end_date
        ).select_related('work_order', 'created_by').prefetch_related('items')

        if status_filter:
            bills = bills.filter(status=status_filter)

        if work_order_id:
            bills = bills.filter(work_order_id=work_order_id)

        # Summary statistics
        total_bills = bills.count()
        total_amount = bills.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        total_advance_deducted = bills.aggregate(Sum('advance_deducted'))['advance_deducted__sum'] or 0
        total_net_payable = bills.aggregate(Sum('net_payable'))['net_payable__sum'] or 0
        total_paid = bills.aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
        total_balance = bills.aggregate(Sum('balance'))['balance__sum'] or 0

        # Status breakdown
        generated_count = bills.filter(status='GENERATED').count()
        paid_count = bills.filter(status='PAID').count()
        cancelled_count = bills.filter(status='CANCELLED').count()

        # Tax statistics
        total_cgst = bills.aggregate(Sum('cgst_amount'))['cgst_amount__sum'] or 0
        total_sgst = bills.aggregate(Sum('sgst_amount'))['sgst_amount__sum'] or 0
        total_igst = bills.aggregate(Sum('igst_amount'))['igst_amount__sum'] or 0

        # Detailed data
        report_data = []
        for bill in bills:
            items_count = bill.items.count()

            report_data.append({
                'bill_number': bill.bill_number,
                'bill_date': bill.bill_date.isoformat(),
                'wo_number': bill.work_order.wo_number,
                'client_name': bill.client_name,
                'contact_person': bill.contact_person,
                'phone': bill.phone,
                'total_items': items_count,
                'subtotal': float(bill.subtotal),
                'tax_summary': {
                    'cgst': float(bill.cgst_amount),
                    'sgst': float(bill.sgst_amount),
                    'igst': float(bill.igst_amount),
                    'total_tax': float(bill.cgst_amount + bill.sgst_amount + bill.igst_amount)
                },
                'total_amount': float(bill.total_amount),
                'advance_deducted': float(bill.advance_deducted),
                'net_payable': float(bill.net_payable),
                'amount_paid': float(bill.amount_paid),
                'balance': float(bill.balance),
                'status': bill.status,
                'created_by': bill.created_by.get_full_name(),
                'created_at': bill.created_at.isoformat()
            })

        return Response({
            'report_type': 'Bill Report',
            'date_range': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'summary': {
                'total_bills': total_bills,
                'total_amount': float(total_amount),
                'total_advance_deducted': float(total_advance_deducted),
                'total_net_payable': float(total_net_payable),
                'total_paid': float(total_paid),
                'total_outstanding': float(total_balance),
                'generated_bills': generated_count,
                'paid_bills': paid_count,
                'cancelled_bills': cancelled_count,
                'tax_collected': {
                    'cgst': float(total_cgst),
                    'sgst': float(total_sgst),
                    'igst': float(total_igst),
                    'total': float(total_cgst + total_sgst + total_igst)
                }
            },
            'bills': report_data,
            'generated_at': datetime.now().isoformat(),
            'generated_by': request.user.get_full_name()
        })


class BillDetailedReportView(BillingReportsBaseView):
    """
    Single Bill Detailed Report

    GET /api/reports/billing/bills/{id}/detailed
    """

    def get(self, request, pk):
        try:
            bill = Bill.objects.select_related('work_order', 'created_by').get(id=pk)
        except Bill.DoesNotExist:
            return Response({'error': 'Bill not found'}, status=404)

        # Items
        items = []
        for item in bill.items.all():
            items.append({
                'item_code': item.item_code,
                'item_name': item.item_name,
                'description': item.description,
                'hsn_code': item.hsn_code,
                'unit': item.unit,
                'ordered_quantity': float(item.ordered_quantity),
                'previously_delivered': float(item.previously_delivered_quantity),
                'delivered_quantity': float(item.delivered_quantity),
                'pending_quantity': float(item.pending_quantity),
                'rate': float(item.rate),
                'amount': float(item.amount),
                'remarks': item.remarks
            })

        return Response({
            'bill_number': bill.bill_number,
            'bill_date': bill.bill_date.isoformat(),
            'work_order': {
                'wo_number': bill.work_order.wo_number,
                'wo_date': bill.work_order.wo_date.isoformat(),
                'status': bill.work_order.status
            },
            'client_details': {
                'name': bill.client_name,
                'contact_person': bill.contact_person,
                'phone': bill.phone,
                'email': bill.email,
                'address': bill.address
            },
            'items': items,
            'total_items': len(items),
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
                'total_tax': float(bill.cgst_amount + bill.sgst_amount + bill.igst_amount),
                'total_amount': float(bill.total_amount),
                'advance_deducted': float(bill.advance_deducted),
                'net_payable': float(bill.net_payable),
                'amount_paid': float(bill.amount_paid),
                'balance': float(bill.balance)
            },
            'status': bill.status,
            'remarks': bill.remarks,
            'created_by': bill.created_by.get_full_name(),
            'created_at': bill.created_at.isoformat(),
            'generated_at': datetime.now().isoformat()
        })


class BillingAnalyticsView(BillingReportsBaseView):
    """
    Billing Analytics & Trends

    GET /api/reports/billing/analytics?start_date=2026-01-01&end_date=2026-02-28
    GET /api/reports/billing/analytics?group_by=month
    """

    def get(self, request):
        start_date, end_date = self.parse_date_range(request)
        group_by = request.query_params.get('group_by', 'month')

        bills = Bill.objects.filter(
            bill_date__gte=start_date,
            bill_date__lte=end_date
        ).exclude(status='CANCELLED')

        # Overall statistics
        total_bills = bills.count()
        total_revenue = bills.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        total_received = bills.aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
        total_outstanding = bills.aggregate(Sum('balance'))['balance__sum'] or 0
        avg_bill_value = bills.aggregate(Avg('total_amount'))['total_amount__avg'] or 0

        # Time-based trends
        if group_by == 'month':
            time_data = bills.annotate(
                period=TruncMonth('bill_date')
            ).values('period').annotate(
                bills_count=Count('id'),
                total_revenue=Sum('total_amount'),
                total_received=Sum('amount_paid'),
                total_outstanding=Sum('balance')
            ).order_by('period')
        elif group_by == 'week':
            time_data = bills.annotate(
                period=TruncWeek('bill_date')
            ).values('period').annotate(
                bills_count=Count('id'),
                total_revenue=Sum('total_amount'),
                total_received=Sum('amount_paid'),
                total_outstanding=Sum('balance')
            ).order_by('period')
        else:  # day
            time_data = bills.annotate(
                period=TruncDate('bill_date')
            ).values('period').annotate(
                bills_count=Count('id'),
                total_revenue=Sum('total_amount'),
                total_received=Sum('amount_paid'),
                total_outstanding=Sum('balance')
            ).order_by('period')

        # Top clients by revenue
        top_clients = bills.values('client_name').annotate(
            total_revenue=Sum('total_amount'),
            total_bills=Count('id'),
            total_paid=Sum('amount_paid'),
            total_outstanding=Sum('balance')
        ).order_by('-total_revenue')[:10]

        # Payment collection rate
        collection_rate = (float(total_received) / float(total_revenue) * 100) if total_revenue > 0 else 0

        # Average time to payment (for paid bills)
        paid_bills = bills.filter(status='PAID')
        avg_payment_days = 0
        if paid_bills.exists():
            payment_times = []
            for bill in paid_bills:
                # Estimate using updated_at as payment date
                days_diff = (bill.updated_at.date() - bill.bill_date).days
                payment_times.append(days_diff)
            avg_payment_days = sum(payment_times) / len(payment_times) if payment_times else 0

        return Response({
            'report_type': 'Billing Analytics',
            'date_range': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'overall_statistics': {
                'total_bills': total_bills,
                'total_revenue': float(total_revenue),
                'total_received': float(total_received),
                'total_outstanding': float(total_outstanding),
                'average_bill_value': float(avg_bill_value),
                'collection_rate': round(collection_rate, 2),
                'average_payment_days': round(avg_payment_days, 1)
            },
            'time_trends': [{
                'period': item['period'].strftime('%Y-%m-%d'),
                'bills_count': item['bills_count'],
                'total_revenue': float(item['total_revenue']),
                'total_received': float(item['total_received']),
                'total_outstanding': float(item['total_outstanding'])
            } for item in time_data],
            'top_clients': [{
                'client_name': item['client_name'],
                'total_revenue': float(item['total_revenue']),
                'total_bills': item['total_bills'],
                'total_paid': float(item['total_paid']),
                'total_outstanding': float(item['total_outstanding'])
            } for item in top_clients],
            'generated_at': datetime.now().isoformat(),
            'grouped_by': group_by
        })


class OutstandingPaymentsReportView(BillingReportsBaseView):
    """
    Outstanding Payments Report

    GET /api/reports/billing/outstanding
    GET /api/reports/billing/outstanding?aging=true
    """

    def get(self, request):
        aging = request.query_params.get('aging', 'false').lower() == 'true'

        # Get all bills with outstanding balance
        outstanding_bills = Bill.objects.filter(
            balance__gt=0
        ).exclude(status='CANCELLED').select_related('work_order', 'created_by')

        total_outstanding = outstanding_bills.aggregate(Sum('balance'))['balance__sum'] or 0
        total_bills = outstanding_bills.count()

        # Aging analysis (if requested)
        aging_data = {}
        if aging:
            today = datetime.now().date()

            # 0-30 days
            range_0_30 = outstanding_bills.filter(
                bill_date__gte=today - timedelta(days=30)
            )
            aging_data['0_30_days'] = {
                'count': range_0_30.count(),
                'amount': float(range_0_30.aggregate(Sum('balance'))['balance__sum'] or 0)
            }

            # 31-60 days
            range_31_60 = outstanding_bills.filter(
                bill_date__gte=today - timedelta(days=60),
                bill_date__lt=today - timedelta(days=30)
            )
            aging_data['31_60_days'] = {
                'count': range_31_60.count(),
                'amount': float(range_31_60.aggregate(Sum('balance'))['balance__sum'] or 0)
            }

            # 61-90 days
            range_61_90 = outstanding_bills.filter(
                bill_date__gte=today - timedelta(days=90),
                bill_date__lt=today - timedelta(days=60)
            )
            aging_data['61_90_days'] = {
                'count': range_61_90.count(),
                'amount': float(range_61_90.aggregate(Sum('balance'))['balance__sum'] or 0)
            }

            # 90+ days
            range_90_plus = outstanding_bills.filter(
                bill_date__lt=today - timedelta(days=90)
            )
            aging_data['90_plus_days'] = {
                'count': range_90_plus.count(),
                'amount': float(range_90_plus.aggregate(Sum('balance'))['balance__sum'] or 0)
            }

        # Detailed list
        bills_data = []
        for bill in outstanding_bills:
            days_outstanding = (datetime.now().date() - bill.bill_date).days

            bills_data.append({
                'bill_number': bill.bill_number,
                'bill_date': bill.bill_date.isoformat(),
                'wo_number': bill.work_order.wo_number,
                'client_name': bill.client_name,
                'contact_person': bill.contact_person,
                'phone': bill.phone,
                'email': bill.email,
                'total_amount': float(bill.total_amount),
                'amount_paid': float(bill.amount_paid),
                'balance': float(bill.balance),
                'days_outstanding': days_outstanding,
                'status': bill.status
            })

        response_data = {
            'report_type': 'Outstanding Payments Report',
            'summary': {
                'total_outstanding_bills': total_bills,
                'total_outstanding_amount': float(total_outstanding)
            },
            'bills': bills_data,
            'generated_at': datetime.now().isoformat()
        }

        if aging:
            response_data['aging_analysis'] = aging_data

        return Response(response_data)


# ============================================================================
# 2. WORK ORDER REPORTS
# ============================================================================

class WorkOrderReportView(BillingReportsBaseView):
    """
    Complete Work Order Report

    GET /api/reports/work-orders?start_date=2026-01-01&end_date=2026-02-28
    GET /api/reports/work-orders?status=ACTIVE
    """

    def get(self, request):
        start_date, end_date = self.parse_date_range(request)

        # Filters
        status_filter = request.query_params.get('status')

        # Query
        work_orders = WorkOrder.objects.filter(
            wo_date__gte=start_date,
            wo_date__lte=end_date
        ).select_related('sales_quotation', 'created_by').prefetch_related('items')

        if status_filter:
            work_orders = work_orders.filter(status=status_filter)

        # Summary statistics
        total_wos = work_orders.count()
        total_value = work_orders.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        total_advance = work_orders.aggregate(Sum('advance_amount'))['advance_amount__sum'] or 0
        total_delivered = work_orders.aggregate(Sum('total_delivered_value'))['total_delivered_value__sum'] or 0

        # Status breakdown
        active_count = work_orders.filter(status='ACTIVE').count()
        partial_count = work_orders.filter(status='PARTIALLY_DELIVERED').count()
        completed_count = work_orders.filter(status='COMPLETED').count()
        cancelled_count = work_orders.filter(status='CANCELLED').count()

        # Detailed data
        report_data = []
        for wo in work_orders:
            items = wo.items.all()
            total_items = items.count()

            # Calculate completion percentage
            total_ordered = sum(item.ordered_quantity for item in items)
            total_delivered_qty = sum(item.delivered_quantity for item in items)
            completion_pct = (total_delivered_qty / total_ordered * 100) if total_ordered > 0 else 0

            report_data.append({
                'wo_number': wo.wo_number,
                'wo_date': wo.wo_date.isoformat(),
                'quotation_number': wo.sales_quotation.quotation_number,
                'client_name': wo.client_name,
                'contact_person': wo.contact_person,
                'phone': wo.phone,
                'total_items': total_items,
                'total_amount': float(wo.total_amount),
                'advance_amount': float(wo.advance_amount),
                'advance_remaining': float(wo.advance_remaining),
                'total_delivered_value': float(wo.total_delivered_value),
                'completion_percentage': round(completion_pct, 2),
                'status': wo.status,
                'created_by': wo.created_by.get_full_name(),
                'created_at': wo.created_at.isoformat()
            })

        return Response({
            'report_type': 'Work Order Report',
            'date_range': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'summary': {
                'total_work_orders': total_wos,
                'total_value': float(total_value),
                'total_advance_received': float(total_advance),
                'total_delivered_value': float(total_delivered),
                'active_wos': active_count,
                'partially_delivered_wos': partial_count,
                'completed_wos': completed_count,
                'cancelled_wos': cancelled_count
            },
            'work_orders': report_data,
            'generated_at': datetime.now().isoformat(),
            'generated_by': request.user.get_full_name()
        })


class WorkOrderDetailedReportView(BillingReportsBaseView):
    """
    Single Work Order Detailed Report

    GET /api/reports/work-orders/{id}/detailed
    """

    def get(self, request, pk):
        try:
            wo = WorkOrder.objects.select_related(
                'sales_quotation__client_query', 'created_by'
            ).prefetch_related('items', 'bills').get(id=pk)
        except WorkOrder.DoesNotExist:
            return Response({'error': 'Work order not found'}, status=404)

        # Items with delivery status
        items = []
        for item in wo.items.all():
            stock_status = item.get_stock_status()

            items.append({
                'item_code': item.item_code,
                'item_name': item.item_name,
                'description': item.description,
                'hsn_code': item.hsn_code,
                'unit': item.unit,
                'ordered_quantity': float(item.ordered_quantity),
                'delivered_quantity': float(item.delivered_quantity),
                'pending_quantity': float(item.pending_quantity),
                'rate': float(item.rate),
                'amount': float(item.amount),
                'stock_status': stock_status,
                'remarks': item.remarks
            })

        # Bills generated
        bills = []
        for bill in wo.bills.all():
            bills.append({
                'bill_number': bill.bill_number,
                'bill_date': bill.bill_date.isoformat(),
                'total_amount': float(bill.total_amount),
                'advance_deducted': float(bill.advance_deducted),
                'net_payable': float(bill.net_payable),
                'amount_paid': float(bill.amount_paid),
                'balance': float(bill.balance),
                'status': bill.status
            })

        # Calculate completion
        total_ordered = sum(item.ordered_quantity for item in wo.items.all())
        total_delivered = sum(item.delivered_quantity for item in wo.items.all())
        completion_pct = (total_delivered / total_ordered * 100) if total_ordered > 0 else 0

        return Response({
            'wo_number': wo.wo_number,
            'wo_date': wo.wo_date.isoformat(),
            'sales_quotation': {
                'quotation_number': wo.sales_quotation.quotation_number,
                'quotation_date': wo.sales_quotation.quotation_date.isoformat(),
                'client_query_number': wo.sales_quotation.client_query.query_number
            },
            'client_details': {
                'name': wo.client_name,
                'contact_person': wo.contact_person,
                'phone': wo.phone,
                'email': wo.email,
                'address': wo.address
            },
            'items': items,
            'total_items': len(items),
            'financial': {
                'subtotal': float(wo.subtotal),
                'cgst_amount': float(wo.cgst_amount),
                'sgst_amount': float(wo.sgst_amount),
                'igst_amount': float(wo.igst_amount),
                'total_amount': float(wo.total_amount),
                'advance_amount': float(wo.advance_amount),
                'advance_deducted': float(wo.advance_deducted),
                'advance_remaining': float(wo.advance_remaining),
                'total_delivered_value': float(wo.total_delivered_value)
            },
            'bills': bills,
            'total_bills': len(bills),
            'delivery_progress': {
                'completion_percentage': round(completion_pct, 2),
                'total_ordered': float(total_ordered),
                'total_delivered': float(total_delivered),
                'total_pending': float(total_ordered - total_delivered)
            },
            'status': wo.status,
            'remarks': wo.remarks,
            'created_by': wo.created_by.get_full_name(),
            'created_at': wo.created_at.isoformat(),
            'generated_at': datetime.now().isoformat()
        })


class WorkOrderDeliveryAnalysisView(BillingReportsBaseView):
    """
    Work Order Delivery Analysis

    GET /api/reports/work-orders/delivery-analysis?start_date=2026-01-01&end_date=2026-02-28
    """

    def get(self, request):
        start_date, end_date = self.parse_date_range(request)

        work_orders = WorkOrder.objects.filter(
            wo_date__gte=start_date,
            wo_date__lte=end_date
        ).prefetch_related('items')

        # Overall delivery statistics
        total_wos = work_orders.count()
        on_time_deliveries = 0
        delayed_deliveries = 0

        # Item-level statistics
        all_items = WorkOrderItem.objects.filter(work_order__in=work_orders)
        total_items = all_items.count()
        fully_delivered_items = all_items.filter(pending_quantity=0).count()
        partially_delivered_items = all_items.filter(
            delivered_quantity__gt=0,
            pending_quantity__gt=0
        ).count()
        pending_items = all_items.filter(delivered_quantity=0).count()

        # Stock availability analysis
        in_stock_items = all_items.filter(
            stock_available=True,
            pending_quantity__gt=0
        ).count()

        out_of_stock_items = all_items.filter(
            stock_available=False,
            pending_quantity__gt=0
        ).count()

        # Work order delivery status
        wo_delivery_status = []
        for wo in work_orders:
            items = wo.items.all()
            total_ordered = sum(item.ordered_quantity for item in items)
            total_delivered = sum(item.delivered_quantity for item in items)
            completion_pct = (total_delivered / total_ordered * 100) if total_ordered > 0 else 0

            wo_delivery_status.append({
                'wo_number': wo.wo_number,
                'client_name': wo.client_name,
                'total_items': items.count(),
                'fully_delivered': items.filter(pending_quantity=0).count(),
                'partially_delivered': items.filter(
                    delivered_quantity__gt=0,
                    pending_quantity__gt=0
                ).count(),
                'pending': items.filter(delivered_quantity=0).count(),
                'completion_percentage': round(completion_pct, 2),
                'status': wo.status
            })

        return Response({
            'report_type': 'Work Order Delivery Analysis',
            'date_range': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'overall_summary': {
                'total_work_orders': total_wos,
                'completed_wos': work_orders.filter(status='COMPLETED').count(),
                'partially_delivered_wos': work_orders.filter(status='PARTIALLY_DELIVERED').count(),
                'pending_wos': work_orders.filter(status='ACTIVE').count()
            },
            'item_summary': {
                'total_items': total_items,
                'fully_delivered_items': fully_delivered_items,
                'partially_delivered_items': partially_delivered_items,
                'pending_items': pending_items,
                'delivery_rate': round((fully_delivered_items / total_items * 100) if total_items > 0 else 0, 2)
            },
            'stock_analysis': {
                'in_stock_pending_items': in_stock_items,
                'out_of_stock_pending_items': out_of_stock_items
            },
            'work_order_details': wo_delivery_status,
            'generated_at': datetime.now().isoformat()
        })


# ============================================================================
# 3. DASHBOARD STATISTICS
# ============================================================================

class BillingDashboardStatsView(APIView):
    """
    Billing & Work Order Dashboard Statistics

    GET /api/dashboard/billing/stats
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = datetime.now().date()
        last_7_days = today - timedelta(days=7)
        last_30_days = today - timedelta(days=30)
        this_month_start = today.replace(day=1)

        # Work Order Stats
        total_wos = WorkOrder.objects.count()
        active_wos = WorkOrder.objects.filter(status='ACTIVE').count()
        partial_wos = WorkOrder.objects.filter(status='PARTIALLY_DELIVERED').count()
        completed_wos = WorkOrder.objects.filter(status='COMPLETED').count()

        wos_this_month = WorkOrder.objects.filter(
            wo_date__gte=this_month_start
        ).count()

        total_wo_value = WorkOrder.objects.aggregate(
            Sum('total_amount')
        )['total_amount__sum'] or 0

        # Bill Stats
        total_bills = Bill.objects.count()
        generated_bills = Bill.objects.filter(status='GENERATED').count()
        paid_bills = Bill.objects.filter(status='PAID').count()

        bills_this_month = Bill.objects.filter(
            bill_date__gte=this_month_start
        ).count()

        total_billed = Bill.objects.exclude(status='CANCELLED').aggregate(
            Sum('total_amount')
        )['total_amount__sum'] or 0

        total_received = Bill.objects.exclude(status='CANCELLED').aggregate(
            Sum('amount_paid')
        )['amount_paid__sum'] or 0

        total_outstanding = Bill.objects.exclude(status='CANCELLED').aggregate(
            Sum('balance')
        )['balance__sum'] or 0

        # Recent activities
        recent_wos = WorkOrder.objects.select_related('created_by').order_by('-created_at')[:5]
        recent_bills = Bill.objects.select_related('created_by', 'work_order').order_by('-created_at')[:5]

        activities = []

        for wo in recent_wos:
            activities.append({
                'type': 'work_order',
                'action': 'created',
                'title': f"Work Order {wo.wo_number}",
                'description': f"For {wo.client_name} - ₹{wo.total_amount}",
                'date': wo.created_at.isoformat(),
                'link': f'/work-orders/{wo.id}'
            })

        for bill in recent_bills:
            activities.append({
                'type': 'bill',
                'action': 'generated',
                'title': f"Bill {bill.bill_number}",
                'description': f"WO {bill.work_order.wo_number} - ₹{bill.total_amount}",
                'date': bill.created_at.isoformat(),
                'link': f'/bills/{bill.id}'
            })

        activities.sort(key=lambda x: x['date'], reverse=True)

        # Alerts
        alerts = []

        # Pending deliveries
        pending_delivery_wos = WorkOrder.objects.filter(
            status__in=['ACTIVE', 'PARTIALLY_DELIVERED']
        ).count()
        if pending_delivery_wos > 0:
            alerts.append({
                'type': 'warning',
                'category': 'work_order',
                'title': 'Pending Deliveries',
                'message': f"{pending_delivery_wos} work order(s) have pending deliveries",
                'action': 'Process deliveries',
                'link': '/work-orders?status=active'
            })

        # Outstanding payments
        outstanding_bills_count = Bill.objects.filter(
            balance__gt=0
        ).exclude(status='CANCELLED').count()
        if outstanding_bills_count > 0:
            alerts.append({
                'type': 'danger',
                'category': 'billing',
                'title': 'Outstanding Payments',
                'message': f"{outstanding_bills_count} bill(s) with pending payment - ₹{total_outstanding}",
                'action': 'Follow up',
                'link': '/bills?status=pending'
            })

        # Low stock items affecting work orders
        from inventory.models import Product
        low_stock_count = Product.objects.filter(
            current_stock__lte=F('reorder_level'),
            is_active=True
        ).count()
        if low_stock_count > 0:
            alerts.append({
                'type': 'warning',
                'category': 'inventory',
                'title': 'Low Stock Alert',
                'message': f"{low_stock_count} product(s) running low - may affect deliveries",
                'action': 'Check inventory',
                'link': '/inventory?status=low_stock'
            })

        return Response({
            'work_orders': {
                'total': total_wos,
                'active': active_wos,
                'partially_delivered': partial_wos,
                'completed': completed_wos,
                'this_month': wos_this_month,
                'total_value': float(total_wo_value)
            },
            'bills': {
                'total': total_bills,
                'generated': generated_bills,
                'paid': paid_bills,
                'this_month': bills_this_month,
                'total_billed': float(total_billed),
                'total_received': float(total_received),
                'total_outstanding': float(total_outstanding),
                'collection_rate': round((float(total_received) / float(total_billed) * 100) if total_billed > 0 else 0, 2)
            },
            'recent_activities': activities[:10],
            'alerts': alerts,
            'generated_at': datetime.now().isoformat()
        })
