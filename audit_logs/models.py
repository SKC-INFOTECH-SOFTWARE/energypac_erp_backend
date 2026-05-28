from django.db import models
from django.conf import settings
import uuid


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ('CREATE', 'Create'),
        ('UPDATE', 'Update'),
        ('DELETE', 'Delete'),
        ('STATUS_CHANGE', 'Status Change'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='audit_logs'
    )
    user_name = models.CharField(max_length=200, blank=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    model_name = models.CharField(max_length=100, help_text="e.g. PurchaseOrder")
    object_id = models.CharField(max_length=100, help_text="PK of the affected object")
    object_repr = models.CharField(max_length=300, blank=True, help_text="String representation")
    changes = models.JSONField(
        default=dict, blank=True,
        help_text="Dict of field changes: {field: {old: ..., new: ...}}"
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'audit_logs'
        ordering = ['-timestamp']
        verbose_name = 'Audit Log'
        verbose_name_plural = 'Audit Logs'

    def __str__(self):
        return f"{self.timestamp} | {self.user_name} | {self.action} {self.model_name} {self.object_repr}"

    @classmethod
    def log(cls, user, action, instance, changes=None):
        cls.objects.create(
            user=user,
            user_name=user.get_full_name() if user else '',
            action=action,
            model_name=instance.__class__.__name__,
            object_id=str(instance.pk),
            object_repr=str(instance)[:300],
            changes=changes or {},
        )
