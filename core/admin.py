from django.contrib import admin
from .models import Currency, ExchangeRate


@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'symbol', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('code', 'name')
    readonly_fields = ('id', 'created_at', 'updated_at')
    ordering = ('code',)


@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ('rate', 'effective_date', 'is_active', 'remarks', 'updated_by', 'updated_at')
    list_filter = ('is_active', 'effective_date')
    search_fields = ('remarks',)
    readonly_fields = ('id', 'created_at', 'updated_at')
    ordering = ('-effective_date', '-created_at')

    fieldsets = (
        (None, {
            'fields': ('rate', 'effective_date', 'is_active', 'remarks')
        }),
        ('Audit', {
            'fields': ('updated_by', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
