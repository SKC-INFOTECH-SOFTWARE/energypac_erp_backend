from django.contrib import admin
from .models import TaxInvoice, TaxInvoiceItem


class TaxInvoiceItemInline(admin.TabularInline):
    model = TaxInvoiceItem
    extra = 0


@admin.register(TaxInvoice)
class TaxInvoiceAdmin(admin.ModelAdmin):
    list_display = ('ti_number', 'kind', 'proforma_invoice', 'invoice_no',
                    'total_amount_after_tax', 'status', 'created_at')
    search_fields = ('ti_number', 'invoice_no', 'proforma_invoice__pi_number',
                     'bill_to_name')
    list_filter = ('kind', 'status')
    inlines = [TaxInvoiceItemInline]
