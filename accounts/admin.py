from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, UserModulePermission


class UserModulePermissionInline(admin.TabularInline):
    model = UserModulePermission
    extra = 0
    max_num = 4


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['employee_code', 'username', 'email', 'first_name', 'last_name',
                    'department', 'role', 'is_active', 'date_joined']
    list_filter = ['is_active', 'is_staff', 'role', 'department', 'date_joined']
    search_fields = ['employee_code', 'username', 'email', 'first_name', 'last_name']
    ordering = ['-date_joined']
    inlines = [UserModulePermissionInline]

    fieldsets = BaseUserAdmin.fieldsets + (
        ('Additional Info', {
            'fields': ('employee_code', 'phone', 'department', 'role')
        }),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('Additional Info', {
            'fields': ('employee_code', 'phone', 'department', 'role')
        }),
    )


@admin.register(UserModulePermission)
class UserModulePermissionAdmin(admin.ModelAdmin):
    list_display = ['user', 'module', 'can_read', 'can_write']
    list_filter = ['module', 'can_read', 'can_write']
    search_fields = ['user__employee_code', 'user__first_name']
