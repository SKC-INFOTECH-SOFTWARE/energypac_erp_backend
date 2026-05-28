from django.contrib import admin
from .models import PIBill, PIBillItem, PIBillPayment


class PIBillItemInline(admin.TabularInline):
    model = PIBillItem
    extra = 0
    readonly_fields = ['amount']
    fields = ['pi_item', 'product', 'item_name', 'hsn_code', 'unit', 'quantity', 'rate', 'amount']


class PIBillPaymentInline(admin.TabularInline):
    model = PIBillPayment
    extra = 0
    readonly_fields = ['payment_number', 'total_paid_after', 'balance_after', 'recorded_by', 'created_at']
    fields = [
        'payment_number', 'amount', 'payment_date', 'payment_mode',
        'reference_number', 'remarks', 'total_paid_after', 'balance_after',
        'recorded_by', 'created_at',
    ]


@admin.register(PIBill)
class PIBillAdmin(admin.ModelAdmin):
    list_display = [
        'bill_number', 'client_name', 'bill_date', 'bill_type',
        'currency', 'total_amount', 'net_payable', 'amount_paid',
        'balance', 'status', 'created_at',
    ]
    list_filter = ['status', 'bill_type', 'bill_date', 'created_at']
    search_fields = ['bill_number', 'client_name', 'proforma_invoice__pi_number']
    readonly_fields = [
        'bill_number', 'subtotal', 'cgst_amount', 'sgst_amount', 'igst_amount',
        'total_amount', 'net_payable', 'balance', 'created_at', 'updated_at',
    ]
    raw_id_fields = ['proforma_invoice', 'created_by']
    inlines = [PIBillItemInline, PIBillPaymentInline]
    ordering = ['-bill_number']
    date_hierarchy = 'bill_date'
    list_per_page = 50

    fieldsets = (
        ('Bill Details', {
            'fields': ('bill_number', 'proforma_invoice', 'bill_date', 'bill_type', 'status')
        }),
        ('Client Information', {
            'fields': ('client_name', 'contact_person', 'phone', 'email', 'address')
        }),
        ('Currency & Financial Details', {
            'fields': (
                'currency', 'conversion_rate', 'subtotal',
                'cgst_percentage', 'sgst_percentage', 'igst_percentage',
                'cgst_amount', 'sgst_amount', 'igst_amount',
                'discount_amount', 'total_amount',
            )
        }),
        ('Payment', {
            'fields': ('net_payable', 'amount_paid', 'balance')
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


@admin.register(PIBillPayment)
class PIBillPaymentAdmin(admin.ModelAdmin):
    list_display = ['pi_bill', 'payment_number', 'amount', 'payment_date', 'payment_mode', 'recorded_by', 'created_at']
    list_filter = ['payment_mode', 'payment_date']
    search_fields = ['pi_bill__bill_number', 'reference_number']
    readonly_fields = ['payment_number', 'total_paid_after', 'balance_after', 'recorded_by', 'created_at']
    raw_id_fields = ['pi_bill']
    ordering = ['-created_at']


@admin.register(PIBillItem)
class PIBillItemAdmin(admin.ModelAdmin):
    list_display = ['pi_bill', 'item_name', 'quantity', 'rate', 'amount']
    list_filter = ['pi_bill__status']
    search_fields = ['item_name', 'pi_bill__bill_number']
    readonly_fields = ['amount']
