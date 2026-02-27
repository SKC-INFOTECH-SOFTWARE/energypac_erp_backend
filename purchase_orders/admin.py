from django.contrib import admin
from .models import PurchaseOrder, PurchaseOrderItem


class PurchaseOrderItemInline(admin.TabularInline):
    model          = PurchaseOrderItem
    extra          = 0
    readonly_fields = ['amount']


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display  = [
        'po_number', 'vendor', 'po_date', 'total_amount', 'status', 'cancelled_at'
    ]
    list_filter   = ['status', 'po_date']
    search_fields = ['po_number', 'vendor__vendor_name']
    readonly_fields = [
        'po_number', 'total_amount',
        'cancelled_by', 'cancelled_at',
        'created_at', 'updated_at',
    ]
    inlines = [PurchaseOrderItemInline]

    fieldsets = (
        ('PO Details', {
            'fields': ('po_number', 'requisition', 'vendor', 'po_date', 'remarks', 'status')
        }),
        ('Financial', {
            'fields': ('total_amount',)
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
