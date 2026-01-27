from django.contrib import admin
from .models import (Requisition, RequisitionItem,
                     VendorRequisitionAssignment, VendorRequisitionItem,
                     VendorQuotation, VendorQuotationItem)

class RequisitionItemInline(admin.TabularInline):
    model = RequisitionItem
    extra = 0
    readonly_fields = ['created_at']
    raw_id_fields = ['product']

@admin.register(Requisition)
class RequisitionAdmin(admin.ModelAdmin):
    list_display = ['requisition_number', 'requisition_date', 'created_by',
                    'is_assigned', 'created_at']
    list_filter = ['is_assigned', 'requisition_date', 'created_at']
    search_fields = ['requisition_number', 'remarks', 'created_by__employee_code']
    readonly_fields = ['requisition_number', 'is_assigned', 'created_at', 'updated_at']
    inlines = [RequisitionItemInline]
    date_hierarchy = 'requisition_date'
    list_per_page = 50

    fieldsets = (
        ('Requisition Details', {
            'fields': ('requisition_number', 'requisition_date', 'remarks')
        }),
        ('Status', {
            'fields': ('is_assigned',)
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def has_delete_permission(self, request, obj=None):
        return False  # Cannot delete requisitions


class VendorRequisitionItemInline(admin.TabularInline):
    model = VendorRequisitionItem
    extra = 0
    readonly_fields = ['product']
    raw_id_fields = ['requisition_item']

@admin.register(VendorRequisitionAssignment)
class VendorAssignmentAdmin(admin.ModelAdmin):
    list_display = ['requisition', 'vendor', 'assignment_date', 'assigned_by', 'created_at']
    list_filter = ['assignment_date', 'created_at']
    search_fields = ['requisition__requisition_number', 'vendor__vendor_name',
                     'assigned_by__employee_code']
    readonly_fields = ['assignment_date', 'created_at']
    inlines = [VendorRequisitionItemInline]
    raw_id_fields = ['requisition', 'vendor']
    date_hierarchy = 'assignment_date'
    list_per_page = 50

    fieldsets = (
        ('Assignment Details', {
            'fields': ('requisition', 'vendor', 'remarks')
        }),
        ('Audit', {
            'fields': ('assignment_date', 'assigned_by', 'created_at'),
            'classes': ('collapse',)
        }),
    )

    def has_delete_permission(self, request, obj=None):
        return False  # Cannot delete assignments


# ============ QUOTATION ADMIN - UPDATED ============

class VendorQuotationItemInline(admin.TabularInline):
    model = VendorQuotationItem
    extra = 0
    readonly_fields = ['amount']  # FIXED: Only 'amount' field now
    raw_id_fields = ['vendor_item', 'product']
    fields = ['vendor_item', 'product', 'quantity', 'quoted_rate', 'amount', 'remarks']

@admin.register(VendorQuotation)
class VendorQuotationAdmin(admin.ModelAdmin):
    list_display = ['quotation_number', 'assignment', 'quotation_date',
                    'total_amount', 'is_selected', 'created_at']
    list_filter = ['is_selected', 'quotation_date', 'created_at']
    search_fields = ['quotation_number', 'reference_number',
                     'assignment__vendor__vendor_name',
                     'assignment__requisition__requisition_number']
    readonly_fields = ['quotation_number', 'quotation_date', 'total_amount',
                       'created_at', 'updated_at']
    inlines = [VendorQuotationItemInline]
    raw_id_fields = ['assignment']
    date_hierarchy = 'quotation_date'
    list_per_page = 50

    fieldsets = (
        ('Quotation Details', {
            'fields': ('quotation_number', 'assignment', 'quotation_date')
        }),
        ('Vendor Information', {
            'fields': ('reference_number', 'validity_date')
        }),
        ('Terms', {
            'fields': ('payment_terms', 'delivery_terms', 'remarks')
        }),
        ('Amount', {
            'fields': ('total_amount',)
        }),
        ('Status', {
            'fields': ('is_selected',)
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def has_delete_permission(self, request, obj=None):
        return False  # Cannot delete quotations
