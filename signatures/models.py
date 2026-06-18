import uuid
from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

User = get_user_model()


# ============================================================================
# SIGNATURE MODELS
# ============================================================================

class UserSignature(models.Model):
    """Store user signatures for verification"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='signatures')
    signature_file = models.ImageField(upload_to='signatures/%Y/%m/%d/', help_text='PNG or JPG only')
    signature_base64 = models.TextField(help_text='Base64 encoded signature for easy transmission')
    name = models.CharField(max_length=100, default='Official Signature')
    is_active = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'User Signature'
        verbose_name_plural = 'User Signatures'

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.name}"

    def clean(self):
        """Validate file format"""
        if self.signature_file:
            ext = self.signature_file.name.lower().split('.')[-1]
            if ext not in ['png', 'jpg', 'jpeg']:
                raise ValidationError("Only PNG and JPG files are allowed")

            if self.signature_file.size > 5 * 1024 * 1024:  # 5MB
                raise ValidationError("File size must be less than 5MB")


# ============================================================================
# VERIFICATION BASE & SPECIFIC MODELS
# ============================================================================

class VerificationBase(models.Model):
    """Abstract base class for PI and PO verifications"""

    VERIFICATION_TYPE_CHOICES = [
        ('SELF_VERIFICATION', 'Self Verification'),
        ('EXTERNAL_VERIFICATION', 'External Verification'),
        ('CHAIN_VERIFICATION', 'Chain Verification'),
    ]

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('VERIFIED', 'Verified'),
        ('REJECTED', 'Rejected'),
        ('EXPIRED', 'Expired'),
    ]

    VERIFIER_ROLE_CHOICES = [
        ('CHECKED_BY', 'Checked By'),
        ('AUTHORIZED_SIGNATORY', 'Authorized Signatory'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='%(class)s_created')
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='%(class)s_assigned', help_text='Deprecated: use verifiers field instead')
    verification_type = models.CharField(max_length=30, choices=VERIFICATION_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    verified_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    rejection_reason = models.TextField(null=True, blank=True)
    signature = models.ForeignKey(UserSignature, on_delete=models.SET_NULL, null=True, blank=True)
    signature_position = models.IntegerField(default=1)
    verification_chain = models.JSONField(default=list, help_text='Array of all signatures in chain')
    # New field: Array of verifiers with roles [{user_id, role, status, signature_id, verified_at}, ...]
    verifiers = models.JSONField(default=list, help_text='Array of verifiers with roles and approval status')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']


class PIVerification(VerificationBase):
    """Track PI verification and signatures"""

    pi = models.ForeignKey('sales.ProformaInvoice', on_delete=models.CASCADE, related_name='verifications')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'PI Verification'
        verbose_name_plural = 'PI Verifications'

    def __str__(self):
        return f"PI {self.pi.id} - {self.get_status_display()}"


class POVerification(VerificationBase):
    """Track PO verification and signatures"""

    from purchase_orders.models import PurchaseOrder

    po = models.ForeignKey('purchase_orders.PurchaseOrder', on_delete=models.CASCADE, related_name='verifications')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'PO Verification'
        verbose_name_plural = 'PO Verifications'

    def __str__(self):
        return f"PO {self.po.id} - {self.get_status_display()}"


# ============================================================================
# AUDIT & LOGGING
# ============================================================================

class SignatureLog(models.Model):
    """Audit trail for all signatures"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Generic FK to PI or PO
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField()
    content_object_type = models.CharField(max_length=20, choices=[('PI', 'PI'), ('PO', 'PO')])

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name='signature_logs')
    signature = models.ForeignKey(UserSignature, on_delete=models.PROTECT)
    signature_position = models.IntegerField()

    signed_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    device_info = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['signature_position', 'signed_at']
        verbose_name = 'Signature Log'
        verbose_name_plural = 'Signature Logs'

    def __str__(self):
        return f"{self.user.get_full_name()} signed at position {self.signature_position}"


# ============================================================================
# NOTIFICATIONS
# ============================================================================

class Notification(models.Model):
    """Real-time notifications for verifications"""

    NOTIFICATION_TYPE_CHOICES = [
        ('PI_VERIFICATION_REQUESTED', 'PI Verification Requested'),
        ('PI_VERIFIED', 'PI Verified'),
        ('PI_REJECTED', 'PI Rejected'),
        ('PO_VERIFICATION_REQUESTED', 'PO Verification Requested'),
        ('PO_VERIFIED', 'PO Verified'),
        ('PO_REJECTED', 'PO Rejected'),
        ('SIGNATURE_CHAIN_UPDATED', 'Signature Chain Updated'),
        ('PI_ITEMS_NOT_PURCHASED', 'PI Items Pending Purchase'),
        # Module activity notifications (scoped to users with module access)
        ('REQUISITION_CREATED', 'Requisition Created'),
        ('PURCHASE_ORDER_CREATED', 'Purchase Order Created'),
        ('PI_CREATED', 'Proforma Invoice Created'),
        ('PAYMENT_RECORDED', 'Payment Recorded'),
        ('ADVANCE_PAYMENT_RECORDED', 'Advance Payment Recorded'),
        ('TRANSPORT_CREATED', 'Transport Entry Created'),
        ('SALES_RETURN_CREATED', 'Sales Return Created'),
        ('PURCHASE_RETURN_CREATED', 'Purchase Return Created'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=50, choices=NOTIFICATION_TYPE_CHOICES)

    # Generic FK to PI or PO
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField()

    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='triggered_notifications')
    title = models.CharField(max_length=255)
    message = models.TextField()
    action_url = models.CharField(max_length=500, null=True, blank=True)

    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['is_read']),
        ]
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'

    def __str__(self):
        return f"{self.user.username} - {self.get_notification_type_display()}"
