from django.contrib import admin
from .models import ClientQuery, SalesQuotation, SalesQuotationItem, ProformaInvoice, ProformaInvoiceItem


class ProformaInvoiceItemInline(admin.TabularInline):
    model = ProformaInvoiceItem
    extra = 0
    readonly_fields = ['amount']


@admin.register(ProformaInvoice)
class ProformaInvoiceAdmin(admin.ModelAdmin):
    list_display  = ['pi_number', 'requisition', 'pi_date', 'currency', 'grand_total', 'status']
    list_filter   = ['status', 'currency', 'pi_date']
    search_fields = ['pi_number', 'requisition__requisition_number']
    readonly_fields = [
        'pi_number', 'grand_total',
        'revision_number', 'is_revised',
        'locked_by', 'locked_at',
        'created_at', 'updated_at',
    ]
    inlines = [ProformaInvoiceItemInline]

    fieldsets = (
        ('PI Details', {
            'fields': ('pi_number', 'requisition', 'pi_date', 'currency', 'status')
        }),
        ('Header Info', {
            'fields': (
                'lc_number', 'exporter_beneficiary', 'exporter_reference',
                'gst_number', 'consignee', 'applicant_importer',
                'pre_carriage_by', 'country_of_origin', 'final_destination',
                'place_of_receipt', 'port_of_loading', 'port_of_discharge',
                'terms_of_delivery', 'terms_of_payment',
            ),
            'classes': ('collapse',),
        }),
        ('Amounts', {
            'fields': ('grand_total',)
        }),
        ('T&C / Notes', {
            'fields': ('terms_and_conditions', 'notes')
        }),
        ('Revision', {
            'fields': ('revision_number', 'is_revised')
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )


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
    readonly_fields = ['amount']
    fields = [
        'product', 'item_code', 'item_name', 'quantity',
        'unit', 'rate', 'amount', 'remarks'
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
        'quotation_number',
        'subtotal', 'cgst_amount', 'sgst_amount', 'igst_amount', 'total_amount',
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
        ('Currency & Amounts', {
            'fields': ('currency',)
        }),
        ('GST Configuration', {
            'fields': ('cgst_percentage', 'sgst_percentage', 'igst_percentage')
        }),
        ('Amounts', {
            'fields': (
                'subtotal', 'cgst_amount', 'sgst_amount',
                'igst_amount', 'total_amount'
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
