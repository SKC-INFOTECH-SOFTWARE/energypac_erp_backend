from rest_framework import generics, permissions, viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from django_filters.rest_framework import DjangoFilterBackend
from django.core.mail import send_mail
from django.conf import settings

from .models import User, UserModulePermission, MODULE_CHOICES, PasswordResetOTP
from .serializers import (
    CustomTokenObtainPairSerializer,
    UserSerializer,
    UserModulePermissionSerializer,
    AdminUserCreateSerializer,
    AdminUserUpdateSerializer,
    ForgotPasswordSerializer,
    VerifyOTPSerializer,
    ResetPasswordSerializer,
)
from core.permissions import IsAdmin


class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [permissions.AllowAny]


class ForgotPasswordView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']
        user = User.objects.get(email=email, is_active=True)
        otp_record = PasswordResetOTP.generate_otp(user)

        send_mail(
            subject='Password Reset OTP - EnergyPac ERP',
            message=f'Your OTP for password reset is: {otp_record.otp}\n\nThis OTP is valid for 10 minutes.\n\nIf you did not request this, please ignore this email.',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )

        return Response({
            'message': 'OTP sent to your email address.',
            'email': email,
        })


class VerifyOTPView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        otp_record = serializer.validated_data['otp_record']
        otp_record.is_verified = True
        otp_record.save()

        return Response({
            'message': 'OTP verified successfully.',
            'email': serializer.validated_data['email'],
        })


class ResetPasswordView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data['user']
        otp_record = serializer.validated_data['otp_record']

        user.set_password(serializer.validated_data['new_password'])
        user.save()

        otp_record.delete()

        return Response({
            'message': 'Password reset successfully. You can now login with your new password.',
        })


class ProfileView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class AdminUserViewSet(viewsets.ModelViewSet):
    """
    Admin-only CRUD for managing users and their module permissions.

    GET    /api/admin/users                          - List all users
    POST   /api/admin/users                          - Create user with permissions
    GET    /api/admin/users/{id}                     - Get user detail
    PUT    /api/admin/users/{id}                     - Full update
    PATCH  /api/admin/users/{id}                     - Partial update
    DELETE /api/admin/users/{id}                     - Deactivate user

    POST   /api/admin/users/{id}/reset_password      - Reset user password
    PATCH  /api/admin/users/{id}/update_permissions   - Update permissions only
    PATCH  /api/admin/users/{id}/toggle_active        - Toggle active/inactive
    GET    /api/admin/users/modules                   - List available modules
    GET    /api/admin/users/stats                     - User statistics
    """
    queryset = User.objects.prefetch_related('module_permissions').all()
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['role', 'is_active', 'department']
    search_fields = ['employee_code', 'username', 'first_name', 'last_name', 'email']
    ordering_fields = ['employee_code', 'created_at', 'first_name']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return AdminUserCreateSerializer
        if self.action in ('update', 'partial_update'):
            return AdminUserUpdateSerializer
        return UserSerializer

    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        if user.id == request.user.id:
            return Response(
                {'error': 'You cannot deactivate your own account.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        user.is_active = False
        user.save()
        return Response({
            'message': f'User {user.employee_code} has been deactivated.',
            'user': UserSerializer(user).data
        })

    @action(detail=True, methods=['post'])
    def reset_password(self, request, pk=None):
        """Reset a user's password (admin only)."""
        user = self.get_object()
        new_password = request.data.get('new_password')
        if not new_password or len(new_password) < 6:
            return Response(
                {'error': 'new_password is required (minimum 6 characters).'},
                status=status.HTTP_400_BAD_REQUEST
            )
        user.set_password(new_password)
        user.save()
        return Response({
            'message': f'Password reset successfully for {user.employee_code}.'
        })

    @action(detail=True, methods=['patch'])
    def update_permissions(self, request, pk=None):
        """Update module permissions for a user."""
        user = self.get_object()
        permissions_data = request.data.get('permissions', [])

        if not isinstance(permissions_data, list):
            return Response(
                {'error': 'permissions must be an array.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.module_permissions.all().delete()

        if user.role == 'ADMIN':
            for module_key, _ in MODULE_CHOICES:
                UserModulePermission.objects.create(
                    user=user, module=module_key, can_read=True, can_write=True
                )
        else:
            serializer = UserModulePermissionSerializer(data=permissions_data, many=True)
            serializer.is_valid(raise_exception=True)
            for perm_data in serializer.validated_data:
                UserModulePermission.objects.create(user=user, **perm_data)

        user.refresh_from_db()
        return Response({
            'message': f'Permissions updated for {user.employee_code}.',
            'user': UserSerializer(user).data
        })

    @action(detail=True, methods=['patch'])
    def toggle_active(self, request, pk=None):
        """Activate or deactivate a user."""
        user = self.get_object()
        if user.id == request.user.id:
            return Response(
                {'error': 'You cannot deactivate your own account.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        user.is_active = not user.is_active
        user.save()
        return Response({
            'message': f'User {user.employee_code} {"activated" if user.is_active else "deactivated"}.',
            'is_active': user.is_active
        })

    @action(detail=False, methods=['get'])
    def modules(self, request):
        """List all available modules with their keys."""
        return Response({
            'modules': [
                {'key': key, 'label': label}
                for key, label in MODULE_CHOICES
            ]
        })

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """User statistics for admin dashboard."""
        total = User.objects.count()
        active = User.objects.filter(is_active=True).count()
        admins = User.objects.filter(role='ADMIN', is_active=True).count()
        employees = User.objects.filter(role='EMPLOYEE', is_active=True).count()
        return Response({
            'total_users': total,
            'active_users': active,
            'inactive_users': total - active,
            'admin_count': admins,
            'employee_count': employees,
        })
