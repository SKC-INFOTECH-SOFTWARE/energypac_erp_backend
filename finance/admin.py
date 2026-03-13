from django.contrib import admin
from .models import PurchasePayment, IncomingPayment


@admin.register(PurchasePayment)
class PurchasePaymentAdmin(admin.ModelAdmin):
    list_display = [
        'purchase_order', 'payment_number', 'amount',
        'payment_date', 'payment_mode', 'payment_status',
        'total_paid_after', 'balance_after', 'recorded_by',
    ]
    list_filter = ['payment_mode', 'payment_status', 'payment_date']
    search_fields = [
        'purchase_order__po_number',
        'purchase_order__vendor__vendor_name',
        'reference_number',
    ]
    readonly_fields = ['id', 'created_at']
    ordering = ['-created_at']


@admin.register(IncomingPayment)
class IncomingPaymentAdmin(admin.ModelAdmin):
    list_display = [
        'bill', 'payment_number', 'amount',
        'payment_date', 'payment_mode', 'payment_status',
        'total_paid_after', 'balance_after', 'recorded_by',
    ]
    list_filter = ['payment_mode', 'payment_status', 'payment_date']
    search_fields = [
        'bill__bill_number',
        'bill__client_name',
        'reference_number',
    ]
    readonly_fields = ['id', 'created_at']
    ordering = ['-created_at']
