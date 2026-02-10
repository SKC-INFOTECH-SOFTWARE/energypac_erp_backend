"""
Sales Reports & Analytics
Complete reporting and statistics for sales module
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count, Q, F, Avg, Max, Min
from django.db.models.functions import TruncMonth, TruncWeek, TruncDate
from datetime import datetime, timedelta
from decimal import Decimal

from sales.models import ClientQuery, SalesQuotation, SalesQuotationItem
from inventory.models import Product


class SalesReportsBaseView(APIView):
    """Base class for all sales reports"""
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
# 1. CLIENT QUERY REPORTS
# ============================================================================

class ClientQueryReportView(SalesReportsBaseView):
    """
    Complete Client Query Report

    GET /api/reports/sales/client-queries?start_date=2026-01-01&end_date=2026-02-28
    GET /api/reports/sales/client-queries?status=PENDING
    GET /api/reports/sales/client-queries?created_by=user_id
    """

    def get(self, request):
        start_date, end_date = self.parse_date_range(request)

        # Filters
        status = request.query_params.get('status')
        created_by = request.query_params.get('created_by')

        # Query
        queries = ClientQuery.objects.filter(
            query_date__gte=start_date,
            query_date__lte=end_date
        ).select_related('created_by').prefetch_related('quotations')

        if status:
            queries = queries.filter(status=status)

        if created_by:
            queries = queries.filter(created_by_id=created_by)

        # Summary statistics
        total_queries = queries.count()
        pending_queries = queries.filter(status='PENDING').count()
        quotation_sent = queries.filter(status='QUOTATION_SENT').count()
        converted_queries = queries.filter(status='CONVERTED').count()
        rejected_queries = queries.filter(status='REJECTED').count()

        # Conversion rate
        conversion_rate = (converted_queries / total_queries * 100) if total_queries > 0 else 0

        # Detailed data
        report_data = []
        for query in queries:
            quotations = query.quotations.all()
            total_quoted = sum(q.total_amount for q in quotations)

            report_data.append({
                'query_number': query.query_number,
                'query_date': query.query_date.isoformat(),
                'client_name': query.client_name,
                'contact_person': query.contact_person,
                'phone': query.phone,
                'email': query.email,
                'status': query.status,
                'has_pdf': bool(query.pdf_file),
                'quotations_count': quotations.count(),
                'total_quoted_amount': float(total_quoted),
                'created_by': query.created_by.get_full_name(),
                'created_at': query.created_at.isoformat(),
                'remarks': query.remarks
            })

        return Response({
            'report_type': 'Client Query Report',
            'date_range': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'summary': {
                'total_queries': total_queries,
                'pending_queries': pending_queries,
                'quotation_sent': quotation_sent,
                'converted_queries': converted_queries,
                'rejected_queries': rejected_queries,
                'conversion_rate': round(conversion_rate, 2)
            },
            'queries': report_data,
            'generated_at': datetime.now().isoformat(),
            'generated_by': request.user.get_full_name()
        })


class ClientQueryDetailedReportView(SalesReportsBaseView):
    """
    Single Client Query Detailed Report

    GET /api/reports/sales/client-queries/{id}/detailed
    """

    def get(self, request, pk):
        try:
            query = ClientQuery.objects.select_related('created_by').get(id=pk)
        except ClientQuery.DoesNotExist:
            return Response({'error': 'Client query not found'}, status=404)

        # Get all quotations
        quotations = []
        total_quoted = 0

        for quote in query.quotations.all():
            items = []
            for item in quote.items.all():
                items.append({
                    'item_code': item.item_code,
                    'item_name': item.item_name,
                    'description': item.description,
                    'hsn_code': item.hsn_code,
                    'quantity': float(item.quantity),
                    'unit': item.unit,
                    'rate': float(item.rate),
                    'amount': float(item.amount),
                    'from_stock': item.product is not None
                })

            quotations.append({
                'quotation_number': quote.quotation_number,
                'quotation_date': quote.quotation_date.isoformat(),
                'validity_date': quote.validity_date.isoformat() if quote.validity_date else None,
                'status': quote.status,
                'subtotal': float(quote.subtotal),
                'cgst': {
                    'percentage': float(quote.cgst_percentage),
                    'amount': float(quote.cgst_amount)
                },
                'sgst': {
                    'percentage': float(quote.sgst_percentage),
                    'amount': float(quote.sgst_amount)
                },
                'igst': {
                    'percentage': float(quote.igst_percentage),
                    'amount': float(quote.igst_amount)
                },
                'total_amount': float(quote.total_amount),
                'items': items,
                'payment_terms': quote.payment_terms,
                'delivery_terms': quote.delivery_terms,
                'remarks': quote.remarks
            })

            total_quoted += quote.total_amount

        return Response({
            'query_number': query.query_number,
            'query_date': query.query_date.isoformat(),
            'client_details': {
                'name': query.client_name,
                'contact_person': query.contact_person,
                'phone': query.phone,
                'email': query.email,
                'address': query.address
            },
            'status': query.status,
            'has_pdf': bool(query.pdf_file),
            'remarks': query.remarks,
            'quotations': quotations,
            'total_quotations': len(quotations),
            'total_quoted_amount': float(total_quoted),
            'created_by': query.created_by.get_full_name(),
            'created_at': query.created_at.isoformat(),
            'generated_at': datetime.now().isoformat()
        })


# ============================================================================
# 2. SALES QUOTATION REPORTS
# ============================================================================

class SalesQuotationReportView(SalesReportsBaseView):
    """
    Complete Sales Quotation Report

    GET /api/reports/sales/quotations?start_date=2026-01-01&end_date=2026-02-28
    GET /api/reports/sales/quotations?status=SENT
    GET /api/reports/sales/quotations?client=client_name
    """

    def get(self, request):
        start_date, end_date = self.parse_date_range(request)

        # Filters
        status = request.query_params.get('status')
        client = request.query_params.get('client')

        # Query
        quotations = SalesQuotation.objects.filter(
            quotation_date__gte=start_date,
            quotation_date__lte=end_date
        ).select_related('client_query', 'created_by').prefetch_related('items')

        if status:
            quotations = quotations.filter(status=status)

        if client:
            quotations = quotations.filter(client_query__client_name__icontains=client)

        # Summary statistics
        total_quotations = quotations.count()
        total_value = quotations.aggregate(Sum('total_amount'))['total_amount__sum'] or 0

        draft_count = quotations.filter(status='DRAFT').count()
        sent_count = quotations.filter(status='SENT').count()
        accepted_count = quotations.filter(status='ACCEPTED').count()
        rejected_count = quotations.filter(status='REJECTED').count()

        # Acceptance rate
        acceptance_rate = (accepted_count / (sent_count + accepted_count + rejected_count) * 100) \
            if (sent_count + accepted_count + rejected_count) > 0 else 0

        # Average quotation value
        avg_value = quotations.aggregate(Avg('total_amount'))['total_amount__avg'] or 0

        # Tax statistics
        total_cgst = quotations.aggregate(Sum('cgst_amount'))['cgst_amount__sum'] or 0
        total_sgst = quotations.aggregate(Sum('sgst_amount'))['sgst_amount__sum'] or 0
        total_igst = quotations.aggregate(Sum('igst_amount'))['igst_amount__sum'] or 0

        # Detailed data
        report_data = []
        for quote in quotations:
            items_count = quote.items.count()

            report_data.append({
                'quotation_number': quote.quotation_number,
                'quotation_date': quote.quotation_date.isoformat(),
                'validity_date': quote.validity_date.isoformat() if quote.validity_date else None,
                'client_name': quote.client_query.client_name,
                'query_number': quote.client_query.query_number,
                'status': quote.status,
                'total_items': items_count,
                'subtotal': float(quote.subtotal),
                'tax_summary': {
                    'cgst': float(quote.cgst_amount),
                    'sgst': float(quote.sgst_amount),
                    'igst': float(quote.igst_amount),
                    'total_tax': float(quote.cgst_amount + quote.sgst_amount + quote.igst_amount)
                },
                'total_amount': float(quote.total_amount),
                'created_by': quote.created_by.get_full_name(),
                'created_at': quote.created_at.isoformat()
            })

        return Response({
            'report_type': 'Sales Quotation Report',
            'date_range': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'summary': {
                'total_quotations': total_quotations,
                'total_value': float(total_value),
                'average_value': float(avg_value),
                'draft_quotations': draft_count,
                'sent_quotations': sent_count,
                'accepted_quotations': accepted_count,
                'rejected_quotations': rejected_count,
                'acceptance_rate': round(acceptance_rate, 2),
                'tax_collected': {
                    'cgst': float(total_cgst),
                    'sgst': float(total_sgst),
                    'igst': float(total_igst),
                    'total': float(total_cgst + total_sgst + total_igst)
                }
            },
            'quotations': report_data,
            'generated_at': datetime.now().isoformat(),
            'generated_by': request.user.get_full_name()
        })


class QuotationItemsReportView(SalesReportsBaseView):
    """
    Quotation Items Analysis Report

    GET /api/reports/sales/quotation-items?start_date=2026-01-01&end_date=2026-02-28
    GET /api/reports/sales/quotation-items?product=product_id
    """

    def get(self, request):
        start_date, end_date = self.parse_date_range(request)
        product_id = request.query_params.get('product')

        # Query
        items = SalesQuotationItem.objects.filter(
            quotation__quotation_date__gte=start_date,
            quotation__quotation_date__lte=end_date
        ).select_related('quotation__client_query', 'product')

        if product_id:
            items = items.filter(product_id=product_id)

        # Summary
        total_items = items.count()
        total_quantity = items.aggregate(Sum('quantity'))['quantity__sum'] or 0
        total_value = items.aggregate(Sum('amount'))['amount__sum'] or 0

        # Stock vs Manual
        stock_items = items.filter(product__isnull=False).count()
        manual_items = items.filter(product__isnull=True).count()

        # Top products
        top_products = items.values(
            'item_code', 'item_name'
        ).annotate(
            total_qty=Sum('quantity'),
            total_value=Sum('amount'),
            count=Count('id')
        ).order_by('-total_value')[:10]

        # Detailed data
        report_data = []
        for item in items:
            report_data.append({
                'quotation_number': item.quotation.quotation_number,
                'quotation_date': item.quotation.quotation_date.isoformat(),
                'client_name': item.quotation.client_query.client_name,
                'item_code': item.item_code,
                'item_name': item.item_name,
                'description': item.description,
                'hsn_code': item.hsn_code,
                'quantity': float(item.quantity),
                'unit': item.unit,
                'rate': float(item.rate),
                'amount': float(item.amount),
                'from_stock': item.product is not None,
                'product_id': str(item.product.id) if item.product else None
            })

        return Response({
            'report_type': 'Quotation Items Analysis',
            'date_range': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'summary': {
                'total_items': total_items,
                'total_quantity': float(total_quantity),
                'total_value': float(total_value),
                'stock_items': stock_items,
                'manual_items': manual_items
            },
            'top_products': [{
                'item_code': p['item_code'],
                'item_name': p['item_name'],
                'total_quantity': float(p['total_qty']),
                'total_value': float(p['total_value']),
                'quotations_count': p['count']
            } for p in top_products],
            'items': report_data,
            'generated_at': datetime.now().isoformat()
        })


# ============================================================================
# 3. SALES ANALYTICS & STATISTICS
# ============================================================================

class SalesAnalyticsView(SalesReportsBaseView):
    """
    Comprehensive Sales Analytics

    GET /api/reports/sales/analytics?start_date=2026-01-01&end_date=2026-02-28
    GET /api/reports/sales/analytics?group_by=month  # month, week, day
    """

    def get(self, request):
        start_date, end_date = self.parse_date_range(request)
        group_by = request.query_params.get('group_by', 'month')

        # Quotations in date range
        quotations = SalesQuotation.objects.filter(
            quotation_date__gte=start_date,
            quotation_date__lte=end_date
        )

        # Overall statistics
        total_quotations = quotations.count()
        total_value = quotations.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        avg_value = quotations.aggregate(Avg('total_amount'))['total_amount__avg'] or 0
        max_value = quotations.aggregate(Max('total_amount'))['total_amount__max'] or 0
        min_value = quotations.aggregate(Min('total_amount'))['total_amount__min'] or 0

        # Status breakdown
        status_breakdown = quotations.values('status').annotate(
            count=Count('id'),
            total_value=Sum('total_amount')
        )

        # Time-based trends
        if group_by == 'month':
            time_data = quotations.annotate(
                period=TruncMonth('quotation_date')
            ).values('period').annotate(
                quotations_count=Count('id'),
                total_value=Sum('total_amount'),
                avg_value=Avg('total_amount')
            ).order_by('period')
        elif group_by == 'week':
            time_data = quotations.annotate(
                period=TruncWeek('quotation_date')
            ).values('period').annotate(
                quotations_count=Count('id'),
                total_value=Sum('total_amount'),
                avg_value=Avg('total_amount')
            ).order_by('period')
        else:  # day
            time_data = quotations.annotate(
                period=TruncDate('quotation_date')
            ).values('period').annotate(
                quotations_count=Count('id'),
                total_value=Sum('total_amount'),
                avg_value=Avg('total_amount')
            ).order_by('period')

        # Top clients
        top_clients = quotations.values(
            'client_query__client_name'
        ).annotate(
            quotations_count=Count('id'),
            total_value=Sum('total_amount')
        ).order_by('-total_value')[:10]

        # Tax analysis
        tax_analysis = {
            'cgst': {
                'total': float(quotations.aggregate(Sum('cgst_amount'))['cgst_amount__sum'] or 0),
                'avg_percentage': float(quotations.exclude(cgst_percentage=0).aggregate(
                    Avg('cgst_percentage'))['cgst_percentage__avg'] or 0)
            },
            'sgst': {
                'total': float(quotations.aggregate(Sum('sgst_amount'))['sgst_amount__sum'] or 0),
                'avg_percentage': float(quotations.exclude(sgst_percentage=0).aggregate(
                    Avg('sgst_percentage'))['sgst_percentage__avg'] or 0)
            },
            'igst': {
                'total': float(quotations.aggregate(Sum('igst_amount'))['igst_amount__sum'] or 0),
                'avg_percentage': float(quotations.exclude(igst_percentage=0).aggregate(
                    Avg('igst_percentage'))['igst_percentage__avg'] or 0)
            }
        }

        # Conversion funnel
        queries = ClientQuery.objects.filter(
            query_date__gte=start_date,
            query_date__lte=end_date
        )

        funnel = {
            'total_queries': queries.count(),
            'quotations_sent': queries.filter(status='QUOTATION_SENT').count(),
            'converted': queries.filter(status='CONVERTED').count(),
            'rejected': queries.filter(status='REJECTED').count()
        }

        return Response({
            'report_type': 'Sales Analytics',
            'date_range': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'overall_statistics': {
                'total_quotations': total_quotations,
                'total_value': float(total_value),
                'average_value': float(avg_value),
                'highest_value': float(max_value),
                'lowest_value': float(min_value)
            },
            'status_breakdown': [{
                'status': item['status'],
                'count': item['count'],
                'total_value': float(item['total_value'] or 0)
            } for item in status_breakdown],
            'time_trends': [{
                'period': item['period'].strftime('%Y-%m-%d'),
                'quotations_count': item['quotations_count'],
                'total_value': float(item['total_value']),
                'average_value': float(item['avg_value'])
            } for item in time_data],
            'top_clients': [{
                'client_name': item['client_query__client_name'],
                'quotations_count': item['quotations_count'],
                'total_value': float(item['total_value'])
            } for item in top_clients],
            'tax_analysis': tax_analysis,
            'conversion_funnel': funnel,
            'generated_at': datetime.now().isoformat(),
            'grouped_by': group_by
        })


class SalesPerformanceView(SalesReportsBaseView):
    """
    Sales Performance Metrics

    GET /api/reports/sales/performance?start_date=2026-01-01&end_date=2026-02-28
    """

    def get(self, request):
        start_date, end_date = self.parse_date_range(request)

        # Get quotations
        quotations = SalesQuotation.objects.filter(
            quotation_date__gte=start_date,
            quotation_date__lte=end_date
        )

        # Get queries
        queries = ClientQuery.objects.filter(
            query_date__gte=start_date,
            query_date__lte=end_date
        )

        # Performance by user
        user_performance = quotations.values(
            'created_by__id',
            'created_by__username',
            'created_by__first_name',
            'created_by__last_name'
        ).annotate(
            quotations_count=Count('id'),
            total_value=Sum('total_amount'),
            avg_value=Avg('total_amount'),
            accepted_count=Count('id', filter=Q(status='ACCEPTED')),
            rejected_count=Count('id', filter=Q(status='REJECTED'))
        ).order_by('-total_value')

        performance_data = []
        for user in user_performance:
            full_name = f"{user['created_by__first_name']} {user['created_by__last_name']}".strip()
            if not full_name:
                full_name = user['created_by__username']

            acceptance_rate = 0
            if user['quotations_count'] > 0:
                acceptance_rate = (user['accepted_count'] / user['quotations_count']) * 100

            performance_data.append({
                'user_id': str(user['created_by__id']),
                'user_name': full_name,
                'quotations_count': user['quotations_count'],
                'total_value': float(user['total_value'] or 0),
                'average_value': float(user['avg_value'] or 0),
                'accepted_count': user['accepted_count'],
                'rejected_count': user['rejected_count'],
                'acceptance_rate': round(acceptance_rate, 2)
            })

        # Average response time (query to first quotation)
        avg_response_time = []
        for query in queries:
            first_quotation = query.quotations.order_by('created_at').first()
            if first_quotation:
                delta = (first_quotation.created_at.date() - query.query_date).days
                avg_response_time.append(delta)

        avg_days = sum(avg_response_time) / len(avg_response_time) if avg_response_time else 0

        # Win rate
        total_sent = queries.filter(
            Q(status='QUOTATION_SENT') | Q(status='CONVERTED') | Q(status='REJECTED')
        ).count()
        total_won = queries.filter(status='CONVERTED').count()
        win_rate = (total_won / total_sent * 100) if total_sent > 0 else 0

        return Response({
            'report_type': 'Sales Performance',
            'date_range': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'overall_metrics': {
                'total_queries': queries.count(),
                'total_quotations': quotations.count(),
                'average_response_time_days': round(avg_days, 1),
                'win_rate': round(win_rate, 2),
                'total_won': total_won,
                'total_lost': queries.filter(status='REJECTED').count()
            },
            'user_performance': performance_data,
            'generated_at': datetime.now().isoformat()
        })


# ============================================================================
# 4. SALES DASHBOARD STATISTICS
# ============================================================================

class SalesDashboardStatsView(APIView):
    """
    Sales Dashboard Statistics

    GET /api/dashboard/sales/stats

    Returns quick stats for dashboard display
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Date ranges
        today = datetime.now().date()
        last_7_days = today - timedelta(days=7)
        last_30_days = today - timedelta(days=30)
        this_month_start = today.replace(day=1)

        # Client Queries Stats
        total_queries = ClientQuery.objects.count()
        pending_queries = ClientQuery.objects.filter(status='PENDING').count()
        queries_last_7 = ClientQuery.objects.filter(
            query_date__gte=last_7_days
        ).count()
        queries_this_month = ClientQuery.objects.filter(
            query_date__gte=this_month_start
        ).count()

        # Quotation Stats
        total_quotations = SalesQuotation.objects.count()
        draft_quotations = SalesQuotation.objects.filter(status='DRAFT').count()
        sent_quotations = SalesQuotation.objects.filter(status='SENT').count()
        accepted_quotations = SalesQuotation.objects.filter(status='ACCEPTED').count()

        quotations_last_7 = SalesQuotation.objects.filter(
            quotation_date__gte=last_7_days
        ).count()

        quotations_this_month = SalesQuotation.objects.filter(
            quotation_date__gte=this_month_start
        ).count()

        # Value stats
        total_quoted_value = SalesQuotation.objects.aggregate(
            Sum('total_amount')
        )['total_amount__sum'] or 0

        accepted_value = SalesQuotation.objects.filter(
            status='ACCEPTED'
        ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0

        value_this_month = SalesQuotation.objects.filter(
            quotation_date__gte=this_month_start
        ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0

        # Conversion rate
        total_with_quotes = ClientQuery.objects.exclude(status='PENDING').count()
        converted = ClientQuery.objects.filter(status='CONVERTED').count()
        conversion_rate = (converted / total_with_quotes * 100) if total_with_quotes > 0 else 0

        # Recent activities
        recent_queries = ClientQuery.objects.select_related('created_by').order_by(
            '-created_at'
        )[:5]

        recent_quotations = SalesQuotation.objects.select_related(
            'client_query', 'created_by'
        ).order_by('-created_at')[:5]

        activities = []

        for query in recent_queries:
            activities.append({
                'type': 'client_query',
                'action': 'created',
                'title': f"Query {query.query_number}",
                'description': f"From {query.client_name}",
                'date': query.created_at.isoformat(),
                'link': f'/sales/queries/{query.id}'
            })

        for quote in recent_quotations:
            activities.append({
                'type': 'quotation',
                'action': 'created' if quote.status == 'DRAFT' else 'sent',
                'title': f"Quotation {quote.quotation_number}",
                'description': f"For {quote.client_query.client_name} - ₹{quote.total_amount}",
                'date': quote.created_at.isoformat(),
                'link': f'/sales/quotations/{quote.id}'
            })

        # Sort activities by date
        activities.sort(key=lambda x: x['date'], reverse=True)

        # Alerts
        alerts = []

        # Pending queries alert
        if pending_queries > 0:
            alerts.append({
                'type': 'info',
                'category': 'sales',
                'title': 'Pending Client Queries',
                'message': f"{pending_queries} client quer{'y' if pending_queries == 1 else 'ies'} waiting for quotation",
                'action': 'Create quotations',
                'link': '/sales/queries?status=PENDING'
            })

        # Draft quotations alert
        if draft_quotations > 0:
            alerts.append({
                'type': 'warning',
                'category': 'sales',
                'title': 'Draft Quotations',
                'message': f"{draft_quotations} quotation{'s' if draft_quotations != 1 else ''} in draft status",
                'action': 'Send to clients',
                'link': '/sales/quotations?status=DRAFT'
            })

        # Sent quotations pending response
        if sent_quotations > 0:
            alerts.append({
                'type': 'info',
                'category': 'sales',
                'title': 'Awaiting Client Response',
                'message': f"{sent_quotations} quotation{'s' if sent_quotations != 1 else ''} sent and pending client response",
                'action': 'Follow up',
                'link': '/sales/quotations?status=SENT'
            })

        # Top clients this month
        top_clients = SalesQuotation.objects.filter(
            quotation_date__gte=this_month_start
        ).values(
            'client_query__client_name'
        ).annotate(
            total_value=Sum('total_amount'),
            quotations_count=Count('id')
        ).order_by('-total_value')[:5]

        return Response({
            'client_queries': {
                'total': total_queries,
                'pending': pending_queries,
                'last_7_days': queries_last_7,
                'this_month': queries_this_month
            },
            'quotations': {
                'total': total_quotations,
                'draft': draft_quotations,
                'sent': sent_quotations,
                'accepted': accepted_quotations,
                'last_7_days': quotations_last_7,
                'this_month': quotations_this_month
            },
            'values': {
                'total_quoted': float(total_quoted_value),
                'accepted_value': float(accepted_value),
                'this_month_value': float(value_this_month)
            },
            'metrics': {
                'conversion_rate': round(conversion_rate, 2),
                'acceptance_rate': round((accepted_quotations / total_quotations * 100)
                    if total_quotations > 0 else 0, 2)
            },
            'top_clients_this_month': [{
                'client_name': client['client_query__client_name'],
                'total_value': float(client['total_value']),
                'quotations_count': client['quotations_count']
            } for client in top_clients],
            'recent_activities': activities[:10],
            'alerts': alerts,
            'generated_at': datetime.now().isoformat()
        })


# ============================================================================
# 5. PRODUCT-WISE SALES ANALYSIS
# ============================================================================

class ProductSalesAnalysisView(SalesReportsBaseView):
    """
    Product-wise Sales Analysis

    GET /api/reports/sales/products?start_date=2026-01-01&end_date=2026-02-28
    """

    def get(self, request):
        start_date, end_date = self.parse_date_range(request)

        # Get all quotation items in date range
        items = SalesQuotationItem.objects.filter(
            quotation__quotation_date__gte=start_date,
            quotation__quotation_date__lte=end_date
        ).select_related('product', 'quotation')

        # Group by product
        product_analysis = items.values(
            'item_code', 'item_name', 'unit'
        ).annotate(
            total_quantity=Sum('quantity'),
            total_value=Sum('amount'),
            quotations_count=Count('quotation', distinct=True),
            avg_rate=Avg('rate'),
            min_rate=Min('rate'),
            max_rate=Max('rate')
        ).order_by('-total_value')

        # Stock vs Manual breakdown
        stock_products = items.filter(product__isnull=False).values(
            'product__item_code', 'product__item_name'
        ).annotate(
            total_quantity=Sum('quantity'),
            total_value=Sum('amount')
        ).order_by('-total_value')[:10]

        manual_products = items.filter(product__isnull=True).values(
            'item_code', 'item_name'
        ).annotate(
            total_quantity=Sum('quantity'),
            total_value=Sum('amount')
        ).order_by('-total_value')[:10]

        return Response({
            'report_type': 'Product Sales Analysis',
            'date_range': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'summary': {
                'total_products': len(product_analysis),
                'total_quantity_quoted': float(items.aggregate(Sum('quantity'))['quantity__sum'] or 0),
                'total_value_quoted': float(items.aggregate(Sum('amount'))['amount__sum'] or 0)
            },
            'all_products': [{
                'item_code': p['item_code'],
                'item_name': p['item_name'],
                'unit': p['unit'],
                'total_quantity': float(p['total_quantity']),
                'total_value': float(p['total_value']),
                'quotations_count': p['quotations_count'],
                'average_rate': float(p['avg_rate']),
                'min_rate': float(p['min_rate']),
                'max_rate': float(p['max_rate'])
            } for p in product_analysis],
            'top_stock_products': [{
                'item_code': p['product__item_code'],
                'item_name': p['product__item_name'],
                'total_quantity': float(p['total_quantity']),
                'total_value': float(p['total_value'])
            } for p in stock_products],
            'top_manual_products': [{
                'item_code': p['item_code'],
                'item_name': p['item_name'],
                'total_quantity': float(p['total_quantity']),
                'total_value': float(p['total_value'])
            } for p in manual_products],
            'generated_at': datetime.now().isoformat()
        })
