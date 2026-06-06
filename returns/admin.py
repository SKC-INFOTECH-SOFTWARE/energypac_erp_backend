from django.contrib import admin
from .models import SalesReturn, SalesReturnItem, PurchaseReturn, PurchaseReturnItem


class SalesReturnItemInline(admin.TabularInline):
    model = SalesReturnItem
    extra = 0
    readonly_fields = ['amount']


@admin.register(SalesReturn)
class SalesReturnAdmin(admin.ModelAdmin):
    list_display = ['return_number', 'proforma_invoice', 'return_date', 'status', 'total_return_amount', 'credit_note_number']
    list_filter = ['status']
    search_fields = ['return_number', 'proforma_invoice__pi_number']
    inlines = [SalesReturnItemInline]
    readonly_fields = ['return_number', 'credit_note_number', 'total_return_amount', 'approved_by', 'approved_at']


class PurchaseReturnItemInline(admin.TabularInline):
    model = PurchaseReturnItem
    extra = 0
    readonly_fields = ['amount']


@admin.register(PurchaseReturn)
class PurchaseReturnAdmin(admin.ModelAdmin):
    list_display = ['return_number', 'purchase_order', 'return_date', 'status', 'total_return_amount', 'debit_note_number']
    list_filter = ['status']
    search_fields = ['return_number', 'purchase_order__po_number']
    inlines = [PurchaseReturnItemInline]
    readonly_fields = ['return_number', 'debit_note_number', 'total_return_amount', 'approved_by', 'approved_at']
