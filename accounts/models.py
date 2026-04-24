from django.contrib.auth.models import AbstractUser
from django.db import models
import uuid


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
