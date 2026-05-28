from django.db import models
from django.conf import settings
from purchase_orders.models import PurchaseOrder
from sales.models import ProformaInvoice
from core.models import CURRENCY_CHOICES
import uuid
from decimal import Decimal


# ─────────────────────────────────────────────────────────────────────────────
# OUTGOING PAYMENTS  — Payments made to vendors against Purchase Orders
# ─────────────────────────────────────────────────────────────────────────────

class PurchasePayment(models.Model):
    PAYMENT_MODE_CHOICES = [
        ('CASH',   'Cash'),
        ('CHEQUE', 'Cheque'),
        ('NEFT',   'NEFT'),
        ('RTGS',   'RTGS'),
        ('IMPS',   'IMPS'),
        ('UPI',    'UPI'),
        ('OTHER',  'Other'),
    ]

    STATUS_CHOICES = [
        ('COMPLETED', 'Completed'),
        ('PENDING',   'Pending'),
        ('FAILED',    'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE,
        related_name='purchase_payments',
    )

    payment_number = models.PositiveIntegerField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_date = models.DateField()
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES, default='NEFT')
    reference_number = models.CharField(max_length=100, blank=True)
    remarks = models.TextField(blank=True)
    payment_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='COMPLETED')

    total_paid_after = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='purchase_payments_recorded',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'purchase_payments'
        ordering = ['purchase_order', 'payment_number']

    def __str__(self):
        return f"{self.purchase_order.po_number} – Payment #{self.payment_number} – ₹{self.amount}"


# ─────────────────────────────────────────────────────────────────────────────
# PI PAYMENTS  — Payments received from clients against Proforma Invoices
# ─────────────────────────────────────────────────────────────────────────────

class PIPayment(models.Model):
    PAYMENT_MODE_CHOICES = [
        ('CASH',   'Cash'),
        ('CHEQUE', 'Cheque'),
        ('NEFT',   'NEFT'),
        ('RTGS',   'RTGS'),
        ('IMPS',   'IMPS'),
        ('UPI',    'UPI'),
        ('LC',     'Letter of Credit'),
        ('TT',     'Telegraphic Transfer'),
        ('OTHER',  'Other'),
    ]

    STATUS_CHOICES = [
        ('COMPLETED', 'Completed'),
        ('PENDING',   'Pending'),
        ('FAILED',    'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    proforma_invoice = models.ForeignKey(
        ProformaInvoice, on_delete=models.CASCADE,
        related_name='pi_payments',
    )

    payment_number = models.PositiveIntegerField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_date = models.DateField()
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES, default='TT')
    reference_number = models.CharField(max_length=100, blank=True)
    remarks = models.TextField(blank=True)
    payment_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='COMPLETED')

    total_paid_after = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='pi_payments_recorded',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'pi_payments'
        ordering = ['proforma_invoice', 'payment_number']

    def __str__(self):
        return f"{self.proforma_invoice.pi_number} – Payment #{self.payment_number} – {self.amount}"


# ─────────────────────────────────────────────────────────────────────────────
# ADVANCE PAYMENTS  — Advance received from clients (optionally linked to PI)
# ─────────────────────────────────────────────────────────────────────────────

class AdvancePayment(models.Model):
    PAYMENT_MODE_CHOICES = [
        ('CASH',   'Cash'),
        ('CHEQUE', 'Cheque'),
        ('NEFT',   'NEFT'),
        ('RTGS',   'RTGS'),
        ('IMPS',   'IMPS'),
        ('UPI',    'UPI'),
        ('LC',     'Letter of Credit'),
        ('TT',     'Telegraphic Transfer'),
        ('OTHER',  'Other'),
    ]

    STATUS_CHOICES = [
        ('ACTIVE',     'Active'),
        ('FULLY_USED', 'Fully Used'),
        ('REFUNDED',   'Refunded'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    advance_number = models.CharField(max_length=50, unique=True, editable=False)

    client_name = models.CharField(max_length=200)
    proforma_invoice = models.ForeignKey(
        ProformaInvoice, on_delete=models.PROTECT,
        related_name='advance_payments',
    )

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='INR',
                                help_text="Auto-inherited from PI")
    conversion_rate = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True,
        help_text="Auto-inherited from PI at advance time"
    )
    amount_inr = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    amount_used = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    remaining = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    payment_date = models.DateField()
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES, default='TT')
    reference_number = models.CharField(max_length=100, blank=True)
    remarks = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='advance_payments_recorded',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'advance_payments'
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.advance_number:
            from datetime import datetime
            year = datetime.now().year
            last = AdvancePayment.objects.filter(
                advance_number__startswith=f'ADV/{year}/'
            ).order_by('-advance_number').first()
            new_num = int(last.advance_number.split('/')[-1]) + 1 if last else 1
            self.advance_number = f'ADV/{year}/{new_num:04d}'

        if self.currency == 'INR' or not self.conversion_rate:
            self.amount_inr = self.amount
        else:
            self.amount_inr = self.amount * self.conversion_rate

        self.remaining = self.amount - self.amount_used

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.advance_number} – {self.client_name} – {self.amount}"
