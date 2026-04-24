from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsAdmin(BasePermission):
    message = "Admin access required."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'ADMIN'
        )


class ModulePermission(BasePermission):
    module = None

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if user.role == 'ADMIN':
            return True

        try:
            perm = user.module_permissions.get(module=self.module)
        except user.module_permissions.model.DoesNotExist:
            return False

        if request.method in SAFE_METHODS:
            return perm.can_read or perm.can_write
        return perm.can_write


class MasterModulePermission(ModulePermission):
    module = 'MASTER'
    message = "You don't have access to the Master module."


class PurchaseModulePermission(ModulePermission):
    module = 'PURCHASE'
    message = "You don't have access to the Purchase module."


class SalesModulePermission(ModulePermission):
    module = 'SALES'
    message = "You don't have access to the Sales module."


class FinanceModulePermission(ModulePermission):
    module = 'FINANCE'
    message = "You don't have access to the Finance module."
