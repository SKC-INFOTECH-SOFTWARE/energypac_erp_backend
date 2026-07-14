"""
Dedicated Stock endpoints.

    GET /api/stock                → paginated stock register (one row per item)
    GET /api/stock/summary        → KPI totals for the page header
    GET /api/stock/{product_id}   → full purchase + sale ledger of one item

Read-only: nothing here writes stock. Stock is only moved by PO receive,
PI accept and Returns — see inventory.stock_service for the ledger rules.
"""

from decimal import Decimal

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q, F

from core.pagination import SmartPageNumberPagination
from .models import Product
from .stock_service import build_stock_rows, product_ledger, reserved_qty_map, ZERO, _d


SORT_FIELDS = {
    'item_name', 'item_code', 'current_stock', 'available_qty', 'stock_value',
    'last_purchase_rate', 'avg_purchase_rate', 'purchase_count',
    'total_purchased_qty', 'total_sold_qty', 'last_purchase_date',
}


class StockViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    # ── helpers ─────────────────────────────────────────────────────────────

    def _base_queryset(self, request):
        qs = Product.objects.all()

        if request.query_params.get('active_only', 'true').lower() != 'false':
            qs = qs.filter(is_active=True)

        search = (request.query_params.get('search') or '').strip()
        if search:
            qs = qs.filter(
                Q(item_name__icontains=search)
                | Q(item_code__icontains=search)
                | Q(hsn_code__icontains=search)
                | Q(description__icontains=search)
            )
        return qs

    # ── list ────────────────────────────────────────────────────────────────

    def list(self, request):
        """
        Stock register.

        Query params:
            search      — item name / code / HSN
            status      — ALL (default) | IN_STOCK | OUT_OF_STOCK | LOW | SELLABLE | NEVER_PURCHASED
            ordering    — any of SORT_FIELDS, prefix with '-' for descending
            page, page_size
            active_only — 'false' to include inactive items
        """
        qs = self._base_queryset(request)
        stock_filter = (request.query_params.get('status') or 'ALL').upper()

        if stock_filter == 'IN_STOCK':
            qs = qs.filter(current_stock__gt=0)
        elif stock_filter == 'OUT_OF_STOCK':
            qs = qs.filter(current_stock__lte=0)
        elif stock_filter == 'LOW':
            qs = qs.filter(current_stock__gt=0, current_stock__lte=F('reorder_level'))
        elif stock_filter == 'NEVER_PURCHASED':
            qs = qs.filter(purchase_count=0)
        elif stock_filter == 'SELLABLE':
            # available = current_stock − reserved(open PIs); needs the reservation
            # map, so it is resolved in Python over the in-stock candidates only.
            in_stock = list(qs.filter(current_stock__gt=0).values_list('id', 'current_stock'))
            reserved = reserved_qty_map([pid for pid, _ in in_stock])
            sellable_ids = [
                pid for pid, cur in in_stock
                if _d(cur) - reserved.get(pid, ZERO) > ZERO
            ]
            qs = Product.objects.filter(id__in=sellable_ids)

        ordering = (request.query_params.get('ordering') or '-current_stock').strip()
        field = ordering.lstrip('-')
        if field not in SORT_FIELDS:
            ordering, field = '-current_stock', 'current_stock'

        # DB-sortable columns are sorted in SQL; derived ones after row-building.
        db_sortable = {'item_name', 'item_code', 'current_stock',
                       'purchase_count', 'total_purchased_qty', 'last_purchase_date'}
        if field in db_sortable:
            qs = qs.order_by(ordering, 'item_name')
            paginator = SmartPageNumberPagination()
            page = paginator.paginate_queryset(qs, request, view=self)
            rows = build_stock_rows(page)
            return paginator.get_paginated_response(rows)

        # Derived sort (available_qty / stock_value / rates): build every matching
        # row, sort, then page manually so the ordering is globally correct.
        rows = build_stock_rows(qs.order_by('item_name'))
        rows.sort(key=lambda r: (r.get(field) or 0), reverse=ordering.startswith('-'))

        paginator = SmartPageNumberPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(page)

    # ── detail ──────────────────────────────────────────────────────────────

    def retrieve(self, request, pk=None):
        # A malformed UUID raises Django's ValidationError, not DoesNotExist.
        try:
            product = Product.objects.get(pk=pk)
        except (Product.DoesNotExist, DjangoValidationError, ValueError, TypeError):
            return Response({'error': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)
        return Response(product_ledger(product))

    # ── summary KPIs ────────────────────────────────────────────────────────

    @action(detail=False, methods=['get'])
    def summary(self, request):
        qs = self._base_queryset(request)
        rows = build_stock_rows(qs)

        in_stock = [r for r in rows if r['current_stock'] > 0]
        sellable = [r for r in rows if r['available_qty'] > 0]

        total_stock_value = sum(Decimal(str(r['stock_value'])) for r in in_stock)
        total_purchase_value = sum(Decimal(str(r['total_purchase_value'])) for r in rows)
        total_sale_value = sum(Decimal(str(r['total_sale_value'])) for r in rows)
        reserved_units = sum(Decimal(str(r['reserved_qty'])) for r in rows)

        return Response({
            'total_items': len(rows),
            'in_stock_items': len(in_stock),
            'out_of_stock_items': sum(1 for r in rows if r['is_out_of_stock']),
            'low_stock_items': sum(1 for r in rows if r['is_low_stock']),
            'sellable_items': len(sellable),
            'never_purchased_items': sum(1 for r in rows if r['purchase_count'] == 0),
            'total_stock_value': float(round(total_stock_value, 2)),
            'total_purchase_value': float(round(total_purchase_value, 2)),
            'total_sale_value': float(round(total_sale_value, 2)),
            'reserved_units': float(reserved_units),
            'total_stock_units': float(sum(Decimal(str(r['current_stock'])) for r in in_stock)),
        })
