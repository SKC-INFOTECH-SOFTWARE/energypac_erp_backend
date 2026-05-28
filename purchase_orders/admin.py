from django.contrib import admin
from .models import PurchaseOrder, PurchaseOrderItem


class PurchaseOrderItemInline(admin.TabularInline):
    model          = PurchaseOrderItem
    extra          = 0
    readonly_fields = ['amount']


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display  = [
        'po_number', 'vendor', 'po_date', 'currency', 'total_amount', 'status', 'cancelled_at'
    ]
    list_filter   = ['status', 'currency', 'po_date']
    search_fields = ['po_number', 'vendor__vendor_name']
    readonly_fields = [
        'po_number', 'currency',
        'total_amount',
        'cgst_amount', 'sgst_amount', 'igst_amount',
        'cancelled_by', 'cancelled_at',
        'created_at', 'updated_at',
    ]
    inlines = [PurchaseOrderItemInline]

    fieldsets = (
        ('PO Details', {
            'fields': ('po_number', 'requisition', 'vendor', 'po_date', 'subject', 'project_name', 'bill_to', 'ship_to', 'terms_and_conditions', 'remarks', 'status')
        }),
        ('Currency & Financial', {
            'fields': ('currency', 'conversion_rate', 'items_total',
                       'discount_amount',
                       'cgst_percentage', 'sgst_percentage', 'igst_percentage',
                       'cgst_amount', 'sgst_amount', 'igst_amount',
                       'total_amount')
        }),
        ('Revision', {
            'fields': ('revision_number', 'is_revised')
        }),
        ('Cancellation', {
            'fields': ('cancellation_reason', 'cancelled_by', 'cancelled_at'),
            'classes': ('collapse',)
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
