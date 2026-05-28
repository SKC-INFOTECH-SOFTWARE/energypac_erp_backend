from django.contrib import admin
from .models import AuditLog

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['timestamp', 'user_name', 'action', 'model_name', 'object_repr']
    list_filter = ['action', 'model_name', 'timestamp']
    search_fields = ['user_name', 'object_repr']
    readonly_fields = [f.name for f in AuditLog._meta.fields]
