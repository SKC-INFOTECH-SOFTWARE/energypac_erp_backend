from django.contrib import admin
from .models import Bill, BillItem


class BillItemInline(admin.TabularInline):
    model = BillItem
    extra = 0
    readonly_fields = [
        'item_code', 'item_name', 'ordered_quantity',
        'previously_delivered_quantity', 'pending_quantity', 'amount'
    ]
    fields = [
        'work_order_item', 'item_code', 'item_name', 'ordered_quantity',
        'previously_delivered_quantity', 'delivered_quantity',
        'pending_quantity', 'unit', 'rate', 'amount'
    ]


@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = [
        'bill_number', 'client_name', 'bill_date', 'total_amount',
        'net_payable', 'balance', 'status', 'created_at'
    ]
    list_filter = ['status', 'bill_date', 'created_at']
    search_fields = [
        'bill_number', 'client_name', 'work_order__wo_number'
    ]
    readonly_fields = [
        'bill_number', 'work_order', 'subtotal', 'cgst_amount',
        'sgst_amount', 'igst_amount', 'total_amount', 'advance_deducted',
        'net_payable', 'balance', 'created_at', 'updated_at'
    ]
    inlines = [BillItemInline]
    ordering = ['-bill_number']
    date_hierarchy = 'bill_date'
    list_per_page = 50

    fieldsets = (
        ('Bill Details', {
            'fields': (
                'bill_number', 'work_order', 'bill_date', 'status'
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
        ('Advance & Payment', {
            'fields': (
                'advance_deducted', 'net_payable', 'amount_paid', 'balance'
            )
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
        """Prevent deletion of bills"""
        return False


@admin.register(BillItem)
class BillItemAdmin(admin.ModelAdmin):
    list_display = [
        'bill', 'item_code', 'item_name', 'ordered_quantity',
        'delivered_quantity', 'pending_quantity', 'amount'
    ]
    list_filter = ['bill__status']
    search_fields = [
        'item_code', 'item_name', 'bill__bill_number'
    ]
    readonly_fields = [
        'product', 'item_code', 'item_name', 'description',
        'hsn_code', 'unit', 'ordered_quantity',
        'previously_delivered_quantity', 'pending_quantity',
        'rate', 'amount'
    ]

    fieldsets = (
        ('Item Details', {
            'fields': (
                'bill', 'work_order_item', 'product', 'item_code',
                'item_name', 'description', 'hsn_code', 'unit'
            )
        }),
        ('Quantities', {
            'fields': (
                'ordered_quantity', 'previously_delivered_quantity',
                'delivered_quantity', 'pending_quantity'
            )
        }),
        ('Pricing', {
            'fields': ('rate', 'amount')
        }),
        ('Additional', {
            'fields': ('remarks',)
        }),
    )
