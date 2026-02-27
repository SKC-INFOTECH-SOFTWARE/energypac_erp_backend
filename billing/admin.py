from django.contrib import admin
from .models import Bill, BillItem, BillPayment


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


class BillPaymentInline(admin.TabularInline):
    model  = BillPayment
    extra  = 0
    readonly_fields = [
        'payment_number', 'amount', 'payment_date', 'payment_mode',
        'reference_number', 'total_paid_after', 'balance_after',
        'recorded_by', 'created_at',
    ]
    fields = readonly_fields + ['remarks']

    def has_add_permission(self, request, obj=None):
        return False   # payments are created only via mark_paid API

    def has_delete_permission(self, request, obj=None):
        return False   # payment records are immutable


@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = [
        'bill_number', 'client_name', 'bill_date', 'total_amount',
        'net_payable', 'amount_paid', 'balance', 'status', 'created_at'
    ]
    list_filter  = ['status', 'bill_date', 'created_at']
    search_fields = [
        'bill_number', 'client_name', 'work_order__wo_number'
    ]
    readonly_fields = [
        'bill_number', 'work_order', 'subtotal', 'cgst_amount',
        'sgst_amount', 'igst_amount', 'total_amount', 'advance_deducted',
        'net_payable', 'balance', 'created_at', 'updated_at'
    ]
    inlines     = [BillItemInline, BillPaymentInline]
    ordering    = ['-bill_number']
    date_hierarchy = 'bill_date'
    list_per_page  = 50

    fieldsets = (
        ('Bill Details', {
            'fields': ('bill_number', 'work_order', 'bill_date', 'status')
        }),
        ('Client Information', {
            'fields': ('client_name', 'contact_person', 'phone', 'email', 'address')
        }),
        ('Financial Details', {
            'fields': (
                'subtotal',
                'cgst_percentage', 'sgst_percentage', 'igst_percentage',
                'cgst_amount',     'sgst_amount',     'igst_amount',
                'total_amount',
            )
        }),
        ('Advance & Payment', {
            'fields': ('advance_deducted', 'net_payable', 'amount_paid', 'balance')
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
        return False


@admin.register(BillItem)
class BillItemAdmin(admin.ModelAdmin):
    list_display  = [
        'bill', 'item_code', 'item_name', 'ordered_quantity',
        'delivered_quantity', 'pending_quantity', 'amount'
    ]
    list_filter   = ['bill__status']
    search_fields = ['item_code', 'item_name', 'bill__bill_number']
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


@admin.register(BillPayment)
class BillPaymentAdmin(admin.ModelAdmin):
    list_display  = [
        'bill', 'payment_number', 'amount', 'payment_date',
        'payment_mode', 'reference_number', 'total_paid_after',
        'balance_after', 'recorded_by', 'created_at',
    ]
    list_filter   = ['payment_mode', 'payment_date', 'created_at']
    search_fields = [
        'bill__bill_number', 'bill__client_name',
        'reference_number',
    ]
    readonly_fields = [
        'bill', 'payment_number', 'amount', 'payment_date',
        'payment_mode', 'reference_number', 'total_paid_after',
        'balance_after', 'recorded_by', 'created_at',
    ]
    ordering = ['bill', 'payment_number']

    fieldsets = (
        ('Payment Details', {
            'fields': (
                'bill', 'payment_number', 'amount',
                'payment_date', 'payment_mode', 'reference_number',
            )
        }),
        ('Running Totals (snapshot)', {
            'fields': ('total_paid_after', 'balance_after')
        }),
        ('Additional', {
            'fields': ('remarks',)
        }),
        ('Audit', {
            'fields': ('recorded_by', 'created_at'),
            'classes': ('collapse',)
        }),
    )

    def has_add_permission(self, request):
        return False    # only created via API

    def has_delete_permission(self, request, obj=None):
        return False    # immutable audit trail

    def has_change_permission(self, request, obj=None):
        return False    # immutable
