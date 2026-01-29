from django.contrib import admin
from .models import PurchaseOrder, PurchaseOrderItem

class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 0
    readonly_fields = ['amount']

@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ['po_number', 'vendor', 'po_date', 'total_amount', 'status']
    list_filter = ['status', 'po_date']
    search_fields = ['po_number', 'vendor__vendor_name']
    readonly_fields = ['po_number', 'total_amount']
    inlines = [PurchaseOrderItemInline]
