from django.contrib import admin
from .models import UserSignature, PIVerification, POVerification, SignatureLog, Notification


@admin.register(UserSignature)
class UserSignatureAdmin(admin.ModelAdmin):
    list_display = ['user', 'name', 'is_active', 'is_deleted', 'created_at']
    list_filter = ['is_active', 'is_deleted', 'created_at']
    search_fields = ['user__username', 'user__first_name', 'user__last_name', 'name']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(PIVerification)
class PIVerificationAdmin(admin.ModelAdmin):
    list_display = ['pi', 'created_by', 'assigned_to', 'verification_type', 'status', 'verified_at']
    list_filter = ['verification_type', 'status', 'created_at', 'verified_at']
    search_fields = ['pi__proforma_invoice_number', 'created_by__username', 'assigned_to__username']
    readonly_fields = ['id', 'created_at', 'updated_at', 'verification_chain']
    fieldsets = (
        ('Document', {
            'fields': ('pi',)
        }),
        ('Verification Info', {
            'fields': ('created_by', 'assigned_to', 'verification_type', 'status')
        }),
        ('Signature Details', {
            'fields': ('signature', 'signature_position')
        }),
        ('Notes', {
            'fields': ('notes', 'rejection_reason')
        }),
        ('Chain', {
            'fields': ('verification_chain',)
        }),
        ('Timestamps', {
            'fields': ('verified_at', 'expires_at', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(POVerification)
class POVerificationAdmin(admin.ModelAdmin):
    list_display = ['po', 'created_by', 'assigned_to', 'verification_type', 'status', 'verified_at']
    list_filter = ['verification_type', 'status', 'created_at', 'verified_at']
    search_fields = ['po__po_number', 'created_by__username', 'assigned_to__username']
    readonly_fields = ['id', 'created_at', 'updated_at', 'verification_chain']
    fieldsets = (
        ('Document', {
            'fields': ('po',)
        }),
        ('Verification Info', {
            'fields': ('created_by', 'assigned_to', 'verification_type', 'status')
        }),
        ('Signature Details', {
            'fields': ('signature', 'signature_position')
        }),
        ('Notes', {
            'fields': ('notes', 'rejection_reason')
        }),
        ('Chain', {
            'fields': ('verification_chain',)
        }),
        ('Timestamps', {
            'fields': ('verified_at', 'expires_at', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(SignatureLog)
class SignatureLogAdmin(admin.ModelAdmin):
    list_display = ['user', 'signature_position', 'signed_at', 'ip_address']
    list_filter = ['signed_at', 'signature_position']
    search_fields = ['user__username', 'ip_address']
    readonly_fields = ['id', 'created_at', 'device_info']


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'notification_type', 'actor', 'is_read', 'created_at']
    list_filter = ['notification_type', 'is_read', 'created_at']
    search_fields = ['user__username', 'actor__username', 'title', 'message']
    readonly_fields = ['id', 'created_at', 'read_at']
    fieldsets = (
        ('Recipient', {
            'fields': ('user',)
        }),
        ('Notification', {
            'fields': ('notification_type', 'actor', 'title', 'message')
        }),
        ('Action', {
            'fields': ('action_url', 'object_id', 'content_type')
        }),
        ('Status', {
            'fields': ('is_read', 'read_at')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'expires_at'),
            'classes': ('collapse',)
        }),
    )
