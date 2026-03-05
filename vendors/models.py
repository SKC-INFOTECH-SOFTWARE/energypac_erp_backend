from django.db import models
import uuid

class Vendor(models.Model):
    """Vendor Master - Supplier information"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor_code = models.CharField(max_length=50, unique=True,
                                    help_text="Unique vendor code")
    vendor_name = models.CharField(max_length=200,
                                    help_text="Vendor/Supplier name")
    contact_person = models.CharField(max_length=100, blank=True,
                                      help_text="Primary contact person")
    phone = models.CharField(max_length=15, blank=True,
                            help_text="Contact phone number")
    email = models.EmailField(blank=True,
                              help_text="Contact email")
    address = models.TextField(blank=True,
                               help_text="Complete address")
    gst_number = models.CharField(max_length=50, blank=True,
                                  help_text="GST registration number")
    pan_number = models.CharField(max_length=50, blank=True,
                                  help_text="PAN number")

    # ── Banking Details ───────────────────────────────────────────────────────
    bank_name = models.CharField(max_length=100, blank=True)
    account_name = models.CharField(
        max_length=200, blank=True,
        help_text="Name as it appears on the bank account"
    )
    bank_account_number = models.CharField(max_length=50, blank=True)
    ifsc_code = models.CharField(
        max_length=20, blank=True,
        help_text="IFSC code for domestic (NEFT/RTGS/IMPS) transfers"
    )
    swift_code = models.CharField(
        max_length=20, blank=True,
        help_text="SWIFT/BIC code for international wire transfers"
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vendors'
        ordering = ['vendor_name']
        verbose_name = 'Vendor'
        verbose_name_plural = 'Vendors'

    def save(self, *args, **kwargs):
        if not self.vendor_code:
            last = Vendor.objects.order_by('-created_at').first()
            if last and last.vendor_code.startswith('VEN/'):
                try:
                    num = int(last.vendor_code.split('/')[-1]) + 1
                except ValueError:
                    num = Vendor.objects.count() + 1
            else:
                num = Vendor.objects.count() + 1
            self.vendor_code = f'VEN/{num:04d}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.vendor_code} - {self.vendor_name}"
