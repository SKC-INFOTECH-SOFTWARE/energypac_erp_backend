from django.contrib import admin
from .models import WorkOrder, WorkOrderItem


class WorkOrderItemInline(admin.TabularInline):
    model = WorkOrderItem
    extra = 0
    readonly_fields = ['amount', 'delivered_quantity', 'pending_quantity']
    fields = [
        'item_code', 'item_name', 'ordered_quantity', 'delivered_quantity',
        'pending_quantity', 'unit', 'rate', 'amount', 'stock_available', 'stock_quantity'
    ]


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = [
        'wo_number', 'client_name', 'wo_date', 'total_amount',
        'advance_remaining', 'status', 'created_at'
    ]
    list_filter = ['status', 'wo_date', 'created_at']
    search_fields = [
        'wo_number', 'client_name', 'sales_quotation__quotation_number'
    ]
    readonly_fields = [
        'wo_number', 'sales_quotation', 'subtotal', 'cgst_amount',
        'sgst_amount', 'igst_amount', 'total_amount', 'advance_deducted',
        'advance_remaining', 'total_delivered_value', 'created_at', 'updated_at'
    ]
    inlines = [WorkOrderItemInline]
    ordering = ['-wo_number']
    date_hierarchy = 'wo_date'
    list_per_page = 50

    fieldsets = (
        ('Work Order Details', {
            'fields': (
                'wo_number', 'sales_quotation', 'wo_date', 'status'
            )
        }),
        ('Client Information', {
            'fields': (
                'client_name', 'contact_person', 'phone', 'email', 'address'
            )
        }),
        ('Financial Details', {
            'fields': (
                'subtotal', 'cgst_percentage', 'sgst_percentage', 'igst_percentage',
                'cgst_amount', 'sgst_amount', 'igst_amount', 'total_amount'
            )
        }),
        ('Advance Payment', {
            'fields': (
                'advance_amount', 'advance_deducted', 'advance_remaining'
            )
        }),
        ('Delivery Tracking', {
            'fields': ('total_delivered_value',)
        }),
        ('Additional', {
            'fields': ('remarks',)
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of work orders"""
        return False


@admin.register(WorkOrderItem)
class WorkOrderItemAdmin(admin.ModelAdmin):
    list_display = [
        'work_order', 'item_code', 'item_name', 'ordered_quantity',
        'delivered_quantity', 'pending_quantity', 'stock_available'
    ]
    list_filter = ['stock_available', 'work_order__status']
    search_fields = [
        'item_code', 'item_name', 'work_order__wo_number'
    ]
    readonly_fields = ['amount', 'pending_quantity']

    fieldsets = (
        ('Item Details', {
            'fields': (
                'work_order', 'product', 'item_code', 'item_name',
                'description', 'hsn_code', 'unit'
            )
        }),
        ('Quantities', {
            'fields': (
                'ordered_quantity', 'delivered_quantity', 'pending_quantity'
            )
        }),
        ('Pricing', {
            'fields': ('rate', 'amount')
        }),
        ('Stock Info', {
            'fields': ('stock_available', 'stock_quantity')
        }),
        ('Additional', {
            'fields': ('remarks',)
        }),
    )
