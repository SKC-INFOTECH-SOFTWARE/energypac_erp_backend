from django.contrib import admin
from .models import ClientQuery, SalesQuotation, SalesQuotationItem


@admin.register(ClientQuery)
class ClientQueryAdmin(admin.ModelAdmin):
    list_display = [
        'query_number', 'client_name', 'contact_person', 'phone',
        'query_date', 'currency', 'status', 'created_by', 'created_at'
    ]
    list_filter = ['status', 'currency', 'query_date', 'created_at']
    search_fields = [
        'query_number', 'client_name', 'contact_person',
        'email', 'remarks'
    ]
    readonly_fields = ['query_number', 'created_at', 'updated_at']
    ordering = ['-query_number']
    date_hierarchy = 'query_date'
    list_per_page = 50

    fieldsets = (
        ('Query Information', {
            'fields': ('query_number', 'query_date', 'currency', 'status')
        }),
        ('Client Details', {
            'fields': ('client_name', 'contact_person', 'phone', 'email', 'address')
        }),
        ('Query Details', {
            'fields': ('pdf_file', 'remarks')
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def has_delete_permission(self, request, obj=None):
        return False  # Cannot delete client queries


class SalesQuotationItemInline(admin.TabularInline):
    model = SalesQuotationItem
    extra = 0
    readonly_fields = ['amount', 'original_amount']
    fields = [
        'product', 'item_code', 'item_name', 'quantity',
        'unit', 'rate', 'amount', 'original_rate', 'original_amount', 'remarks'
    ]
    raw_id_fields = ['product']


@admin.register(SalesQuotation)
class SalesQuotationAdmin(admin.ModelAdmin):
    list_display = [
        'quotation_number', 'client_query', 'quotation_date',
        'currency', 'subtotal', 'total_amount', 'status', 'created_by', 'created_at'
    ]
    list_filter = ['status', 'quotation_date', 'created_at']
    search_fields = [
        'quotation_number', 'client_query__client_name',
        'client_query__query_number'
    ]
    readonly_fields = [
        'quotation_number', 'exchange_rate',
        'subtotal', 'cgst_amount', 'sgst_amount', 'igst_amount', 'total_amount',
        'original_subtotal', 'original_cgst_amount', 'original_sgst_amount',
        'original_igst_amount', 'original_total_amount',
        'created_at', 'updated_at'
    ]
    raw_id_fields = ['client_query']
    inlines = [SalesQuotationItemInline]
    ordering = ['-quotation_number']
    date_hierarchy = 'quotation_date'
    list_per_page = 50

    fieldsets = (
        ('Quotation Information', {
            'fields': (
                'quotation_number', 'client_query', 'quotation_date',
                'validity_date', 'status'
            )
        }),
        ('Terms & Conditions', {
            'fields': ('payment_terms', 'delivery_terms', 'remarks')
        }),
        ('Currency', {
            'fields': ('currency', 'exchange_rate')
        }),
        ('GST Configuration', {
            'fields': ('cgst_percentage', 'sgst_percentage', 'igst_percentage')
        }),
        ('Amounts (INR)', {
            'fields': (
                'subtotal', 'cgst_amount', 'sgst_amount',
                'igst_amount', 'total_amount'
            ),
            'classes': ('collapse',)
        }),
        ('Original Currency Amounts', {
            'fields': (
                'original_subtotal', 'original_cgst_amount', 'original_sgst_amount',
                'original_igst_amount', 'original_total_amount'
            ),
            'classes': ('collapse',)
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Recalculate totals after saving
        obj.calculate_totals()

    def has_delete_permission(self, request, obj=None):
        return False  # Cannot delete quotations


@admin.register(SalesQuotationItem)
class SalesQuotationItemAdmin(admin.ModelAdmin):
    list_display = [
        'quotation', 'item_code', 'item_name', 'quantity',
        'unit', 'rate', 'amount'
    ]
    list_filter = ['quotation__quotation_date']
    search_fields = [
        'item_code', 'item_name', 'quotation__quotation_number'
    ]
    readonly_fields = ['amount']
    raw_id_fields = ['quotation', 'product']

    fieldsets = (
        ('Item Information', {
            'fields': (
                'quotation', 'product', 'item_code', 'item_name',
                'description', 'hsn_code', 'unit'
            )
        }),
        ('Pricing', {
            'fields': ('quantity', 'rate', 'amount')
        }),
        ('Additional', {
            'fields': ('remarks',)
        }),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Recalculate quotation totals
        obj.quotation.calculate_totals()

    def delete_model(self, request, obj):
        quotation = obj.quotation
        super().delete_model(request, obj)
        # Recalculate quotation totals
        quotation.calculate_totals()
