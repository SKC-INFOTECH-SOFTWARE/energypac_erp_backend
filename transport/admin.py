from django.contrib import admin
from .models import TransportEntry, TransportCostItem


class TransportCostItemInline(admin.TabularInline):
    model = TransportCostItem
    extra = 0


@admin.register(TransportEntry)
class TransportEntryAdmin(admin.ModelAdmin):
    list_display = [
        'transport_number', 'purchase_order', 'proforma_invoice', 'transporter_name',
        'vehicle_number', 'dispatch_date', 'status', 'total_cost', 'created_at',
    ]
    list_filter = ['status', 'dispatch_date', 'created_at']
    search_fields = [
        'transport_number', 'transporter_name', 'vehicle_number',
        'purchase_order__po_number', 'purchase_order__vendor__vendor_name',
    ]
    readonly_fields = ['transport_number', 'total_cost', 'created_at', 'updated_at']
    inlines = [TransportCostItemInline]
    raw_id_fields = ['purchase_order', 'proforma_invoice']
    date_hierarchy = 'dispatch_date'
    list_per_page = 50

    fieldsets = (
        ('Transport Details', {
            'fields': (
                'transport_number', 'purchase_order', 'proforma_invoice', 'status',
            )
        }),
        ('Transporter Info', {
            'fields': (
                'transporter_name', 'transporter_contact',
                'vehicle_number', 'driver_name', 'driver_contact',
            )
        }),
        ('Dispatch & Delivery', {
            'fields': (
                'dispatch_from', 'dispatch_to',
                'dispatch_date', 'expected_delivery_date', 'actual_delivery_date',
            )
        }),
        ('Cost', {
            'fields': ('total_cost',)
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
