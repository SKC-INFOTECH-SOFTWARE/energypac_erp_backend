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


class TransportModulePermission(ModulePermission):
    module = 'TRANSPORT'
    message = "You don't have access to the Transport module."


class ReturnsModulePermission(ModulePermission):
    module = 'RETURNS'
    message = "You don't have access to the Returns module."


class TransportOrFinancePermission(BasePermission):
    """Grants access if the user can use EITHER the Transport OR the Finance module.
    Used for transporter-payment endpoints that live in both the Transport and
    Finance areas."""
    message = "You need Transport or Finance module access."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.role == 'ADMIN':
            return True

        write = request.method not in SAFE_METHODS
        for module in ('TRANSPORT', 'FINANCE'):
            try:
                perm = user.module_permissions.get(module=module)
            except user.module_permissions.model.DoesNotExist:
                continue
            if write:
                if perm.can_write:
                    return True
            elif perm.can_read or perm.can_write:
                return True
        return False


class CurrencyMasterPermission(BasePermission):
    message = "You don't have access to currency master."

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated
