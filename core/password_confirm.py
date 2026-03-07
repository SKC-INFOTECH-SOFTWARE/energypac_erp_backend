"""
core/password_confirm.py
────────────────────────
Re-authentication guard for destructive / sensitive API actions.

Usage
-----
1. Mixin for ViewSet actions (most common):

    class MyViewSet(PasswordConfirmMixin, viewsets.ModelViewSet):

        @action(detail=True, methods=['post'])
        @require_password_confirmation
        def cancel(self, request, pk=None):
            ...

2. Standalone helper (for use inside destroy() overrides):

        def destroy(self, request, *args, **kwargs):
            error = check_password_confirmation(request)
            if error:
                return error
            ...

Request body (all sensitive endpoints):
---------------------------------------
{
    "confirm_password": "<current user's password>",
    ...other fields...
}

Error responses
---------------
400  { "error": "confirm_password is required", "code": "PASSWORD_REQUIRED" }
401  { "error": "Incorrect password.",            "code": "INVALID_PASSWORD"  }
"""

import functools
from rest_framework.response import Response
from rest_framework import status


# ─────────────────────────────────────────────────────────────────────────────
# Low-level helper
# ─────────────────────────────────────────────────────────────────────────────

def check_password_confirmation(request) -> Response | None:
    """
    Validate `confirm_password` in request.data against the authenticated user.

    Returns
    -------
    None            – password is correct, caller may proceed.
    Response(4xx)   – password missing or wrong; caller must return this response.
    """
    confirm_password = request.data.get("confirm_password")

    if not confirm_password:
        return Response(
            {
                "error": "confirm_password is required to perform this action.",
                "code":  "PASSWORD_REQUIRED",
                "hint":  "Include your current password in the request body as 'confirm_password'.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not request.user.check_password(confirm_password):
        return Response(
            {
                "error": "Incorrect password. Action not permitted.",
                "code":  "INVALID_PASSWORD",
            },
            status=status.HTTP_401_UNAUTHORIZED,
        )

    return None   # ✅ all good


# ─────────────────────────────────────────────────────────────────────────────
# Decorator for ViewSet @action methods
# ─────────────────────────────────────────────────────────────────────────────

def require_password_confirmation(view_func):
    """
    Decorator that gates a ViewSet action behind password confirmation.

    Must be placed BELOW @action (i.e., applied first).

    Example
    -------
    @action(detail=True, methods=['post'])
    @require_password_confirmation
    def cancel(self, request, pk=None):
        ...
    """
    @functools.wraps(view_func)
    def wrapper(self, request, *args, **kwargs):
        error = check_password_confirmation(request)
        if error:
            return error
        return view_func(self, request, *args, **kwargs)
    return wrapper


# ─────────────────────────────────────────────────────────────────────────────
# Mixin – add to any ModelViewSet to protect destroy()
# ─────────────────────────────────────────────────────────────────────────────

class PasswordConfirmDestroyMixin:
    """
    Mixin that requires `confirm_password` before the ViewSet's destroy() runs.

    Add as the *first* base class so Python's MRO picks it up before
    ModelViewSet.destroy().

    Example
    -------
    class VendorViewSet(PasswordConfirmDestroyMixin, viewsets.ModelViewSet):
        ...
    """

    def destroy(self, request, *args, **kwargs):
        error = check_password_confirmation(request)
        if error:
            return error
        return super().destroy(request, *args, **kwargs)
