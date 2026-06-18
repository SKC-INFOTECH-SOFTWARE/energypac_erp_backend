from django.contrib import admin
from .models import (
    CommercialInvoice, CommercialInvoiceItem,
    PackingList, PackingListItem,
)


class CommercialInvoiceItemInline(admin.TabularInline):
    model = CommercialInvoiceItem
    extra = 0


@admin.register(CommercialInvoice)
class CommercialInvoiceAdmin(admin.ModelAdmin):
    list_display = ('ci_number', 'proforma_invoice', 'invoice_no', 'currency',
                    'total_cpt_value', 'status', 'created_at')
    search_fields = ('ci_number', 'invoice_no', 'proforma_invoice__pi_number')
    list_filter = ('status', 'currency')
    inlines = [CommercialInvoiceItemInline]


class PackingListItemInline(admin.TabularInline):
    model = PackingListItem
    extra = 0


@admin.register(PackingList)
class PackingListAdmin(admin.ModelAdmin):
    list_display = ('pl_number', 'commercial_invoice', 'total_nett_weight',
                    'total_gross_weight', 'status', 'created_at')
    search_fields = ('pl_number', 'commercial_invoice__ci_number')
    list_filter = ('status',)
    inlines = [PackingListItemInline]
