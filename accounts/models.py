from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
import uuid
import random


ROLE_CHOICES = [
    ('ADMIN', 'Admin'),
    ('EMPLOYEE', 'Employee'),
]

MODULE_CHOICES = [
    ('MASTER', 'Master'),
    ('PURCHASE', 'Purchase'),
    ('SALES', 'Sales'),
    ('FINANCE', 'Finance'),
]


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee_code = models.CharField(max_length=50, unique=True)
    phone = models.CharField(max_length=15, blank=True)
    department = models.CharField(max_length=100, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='EMPLOYEE')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return f"{self.employee_code} - {self.get_full_name()}"

    @property
    def is_admin_user(self):
        return self.role == 'ADMIN'


class UserModulePermission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='module_permissions')
    module = models.CharField(max_length=20, choices=MODULE_CHOICES)
    can_read = models.BooleanField(default=False)
    can_write = models.BooleanField(default=False)

    class Meta:
        db_table = 'user_module_permissions'
        unique_together = ('user', 'module')
        verbose_name = 'User Module Permission'
        verbose_name_plural = 'User Module Permissions'

    def __str__(self):
        perms = []
        if self.can_read:
            perms.append('read')
        if self.can_write:
            perms.append('write')
        return f"{self.user.employee_code} - {self.module}: {', '.join(perms) or 'none'}"


class PasswordResetOTP(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_reset_otps')
    otp = models.CharField(max_length=6)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = 'password_reset_otps'
        ordering = ['-created_at']

    def __str__(self):
        return f"OTP for {self.user.email} - {'verified' if self.is_verified else 'pending'}"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @classmethod
    def generate_otp(cls, user):
        cls.objects.filter(user=user, is_verified=False).delete()
        otp = str(random.randint(100000, 999999))
        instance = cls.objects.create(
            user=user,
            otp=otp,
            expires_at=timezone.now() + timezone.timedelta(minutes=10),
        )
        return instance
