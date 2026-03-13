from django.db import models
from django.conf import settings
from purchase_orders.models import PurchaseOrder
from billing.models import Bill
import uuid
from decimal import Decimal


# ─────────────────────────────────────────────────────────────────────────────
# OUTGOING PAYMENTS  — Payments made to vendors against Purchase Orders
# ─────────────────────────────────────────────────────────────────────────────

class PurchasePayment(models.Model):
    """
    Individual outgoing payment transaction for a Purchase Order.

    When PO items are marked as 'purchased' (received), the amounts
    become payable. This model tracks each payment made to the vendor.
    Supports both full and partial (step-by-step) payments.
    """

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
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name='purchase_payments',
        help_text="Purchase Order this payment is against"
    )

    payment_number = models.PositiveIntegerField(
        help_text="Sequential payment number for this PO"
    )

    amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        help_text="Amount paid in this transaction (INR)"
    )

    payment_date = models.DateField(
        help_text="Date on which payment was made to vendor"
    )

    payment_mode = models.CharField(
        max_length=20, choices=PAYMENT_MODE_CHOICES, default='NEFT'
    )

    reference_number = models.CharField(
        max_length=100, blank=True,
        help_text="Cheque number / UTR / transaction reference"
    )

    remarks = models.TextField(blank=True)

    payment_status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='COMPLETED'
    )

    # Running-total snapshot
    total_paid_after = models.DecimalField(
        max_digits=12, decimal_places=2,
        help_text="Cumulative amount_paid AFTER this transaction (INR)"
    )

    balance_after = models.DecimalField(
        max_digits=12, decimal_places=2,
        help_text="Remaining balance AFTER this transaction (INR)"
    )

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='purchase_payments_recorded'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'purchase_payments'
        ordering = ['purchase_order', 'payment_number']
        verbose_name = 'Purchase Payment'
        verbose_name_plural = 'Purchase Payments'

    def __str__(self):
        return (
            f"{self.purchase_order.po_number} – "
            f"Payment #{self.payment_number} – ₹{self.amount}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# INCOMING PAYMENTS  — Payments received from clients against Bills
# ─────────────────────────────────────────────────────────────────────────────

class IncomingPayment(models.Model):
    """
    Individual incoming payment transaction against a Bill.

    Mirrors the existing BillPayment model but lives in the finance app
    for a unified accounting view. Supports full and partial payments.
    """

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

    bill = models.ForeignKey(
        Bill,
        on_delete=models.CASCADE,
        related_name='incoming_payments',
        help_text="Bill this payment is against"
    )

    payment_number = models.PositiveIntegerField(
        help_text="Sequential payment number for this bill"
    )

    amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        help_text="Amount received in this transaction (INR)"
    )

    payment_date = models.DateField(
        help_text="Date on which payment was received from client"
    )

    payment_mode = models.CharField(
        max_length=20, choices=PAYMENT_MODE_CHOICES, default='CASH'
    )

    reference_number = models.CharField(
        max_length=100, blank=True,
        help_text="Cheque number / UTR / SWIFT reference"
    )

    remarks = models.TextField(blank=True)

    payment_status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='COMPLETED'
    )

    # Running-total snapshot
    total_paid_after = models.DecimalField(
        max_digits=12, decimal_places=2,
        help_text="Cumulative amount_paid AFTER this transaction (INR)"
    )

    balance_after = models.DecimalField(
        max_digits=12, decimal_places=2,
        help_text="Remaining balance AFTER this transaction (INR)"
    )

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='incoming_payments_recorded'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'incoming_payments'
        ordering = ['bill', 'payment_number']
        verbose_name = 'Incoming Payment'
        verbose_name_plural = 'Incoming Payments'

    def __str__(self):
        return (
            f"{self.bill.bill_number} – "
            f"Payment #{self.payment_number} – ₹{self.amount}"
        )
