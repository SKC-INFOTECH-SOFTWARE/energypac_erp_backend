from django.db import models
from django.conf import settings
from datetime import datetime
from decimal import Decimal
import uuid

from sales.models import ProformaInvoice, ProformaInvoiceItem


# ═════════════════════════════════════════════════════════════════════════════
# Domestic Tax Invoice — GST billing doc for DOMESTIC PIs.
# One model covers both the product "TAX INVOICE" and "SERVICE TAX INVOICE"
# (toggled by `kind`). Captures every field shown on the printed form.
# ═════════════════════════════════════════════════════════════════════════════

class TaxInvoice(models.Model):
    KIND_CHOICES = [
        ('PRODUCT', 'Tax Invoice'),
        ('SERVICE', 'Service Tax Invoice'),
    ]
    STATUS_CHOICES = [
        ('DRAFT',          'Draft'),
        ('GENERATED',      'Generated'),
        ('PARTIALLY_PAID', 'Partially Paid'),
        ('PAID',           'Paid'),
        ('CANCELLED',      'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ti_number = models.CharField(max_length=50, unique=True, editable=False)

    proforma_invoice = models.ForeignKey(
        ProformaInvoice, on_delete=models.PROTECT, related_name='tax_invoices',
        null=True, blank=True,   # Service invoices are standalone (no PI)
    )
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default='PRODUCT')

    # ── Company header (editable defaults) ───────────────────────────────────
    company_name    = models.CharField(max_length=200, blank=True, default='')
    company_address = models.TextField(blank=True, default='')
    company_gstin   = models.CharField(max_length=50, blank=True, default='')
    company_pan     = models.CharField(max_length=50, blank=True, default='')
    company_iec     = models.CharField(max_length=50, blank=True, default='')
    copy_label      = models.CharField(max_length=60, blank=True, default='ORIGINAL FOR RECIPIENT')

    # ── Invoice meta ─────────────────────────────────────────────────────────
    invoice_no   = models.CharField(max_length=100, blank=True, default='')
    invoice_date = models.DateField(null=True, blank=True)
    challan_no   = models.CharField(max_length=100, blank=True, default='')   # product
    challan_date = models.DateField(null=True, blank=True)
    state        = models.CharField(max_length=100, blank=True, default='')
    state_code   = models.CharField(max_length=10, blank=True, default='')
    vendor_code  = models.CharField(max_length=100, blank=True, default='')   # product
    vehicle_no       = models.CharField(max_length=100, blank=True, default='')  # product
    mode_of_transport = models.CharField(max_length=100, blank=True, default='')  # product
    place_of_supply  = models.CharField(max_length=300, blank=True, default='')
    buyers_order_no   = models.CharField(max_length=200, blank=True, default='')  # product
    buyers_order_date = models.DateField(null=True, blank=True)
    work_order_no = models.CharField(max_length=200, blank=True, default='')   # service

    # ── Bill To party ────────────────────────────────────────────────────────
    bill_to_name    = models.CharField(max_length=200, blank=True, default='')
    bill_to_address = models.TextField(blank=True, default='')
    bill_to_gstin   = models.CharField(max_length=50, blank=True, default='')
    bill_to_state   = models.CharField(max_length=100, blank=True, default='')

    # ── Shipping address ─────────────────────────────────────────────────────
    ship_to_name    = models.CharField(max_length=200, blank=True, default='')
    ship_to_address = models.TextField(blank=True, default='')
    ship_to_project = models.TextField(blank=True, default='')
    ship_to_state   = models.CharField(max_length=100, blank=True, default='')

    # ── Totals (auto) ────────────────────────────────────────────────────────
    total_amount_before_tax = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_tax_amount        = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_amount_after_tax  = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    amount_in_words         = models.CharField(max_length=500, blank=True, default='')
    gst_on_reverse_charge   = models.CharField(max_length=10, blank=True, default='No')

    # ── Collection (Service invoices are collected in the Finance module) ─────
    amount_paid = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    balance     = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    # ── Bank detail ──────────────────────────────────────────────────────────
    bank_name    = models.CharField(max_length=200, blank=True, default='')
    bank_account = models.CharField(max_length=100, blank=True, default='')
    bank_ifsc    = models.CharField(max_length=50, blank=True, default='')

    terms_of_payment = models.JSONField(default=list, blank=True)

    status     = models.CharField(max_length=20, choices=STATUS_CHOICES, default='GENERATED')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   related_name='tax_invoices_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tax_invoices'
        ordering = ['-ti_number']

    def save(self, *args, **kwargs):
        if not self.ti_number:
            year = datetime.now().year
            prefix = f'TI/{year}/'
            last = TaxInvoice.objects.filter(ti_number__startswith=prefix).order_by('-ti_number').first()
            new_num = int(last.ti_number.split('/')[-1]) + 1 if last else 1
            self.ti_number = f'{prefix}{new_num:04d}'
        super().save(*args, **kwargs)

    def recalc_totals(self):
        items = self.items.all()
        self.total_amount_before_tax = sum((i.taxable_value for i in items), Decimal('0'))
        self.total_tax_amount = sum(
            (i.sgst_amount + i.cgst_amount + i.igst_amount for i in items), Decimal('0')
        )
        self.total_amount_after_tax = self.total_amount_before_tax + self.total_tax_amount
        self.recalc_balance()

    def recalc_balance(self):
        """Keep balance + paid-status in sync with the grand total."""
        self.balance = (self.total_amount_after_tax or Decimal('0')) - (self.amount_paid or Decimal('0'))
        if self.status not in ('CANCELLED', 'DRAFT'):
            if self.amount_paid <= 0:
                self.status = 'GENERATED'
            elif self.balance <= 0:
                self.balance = Decimal('0')
                self.status = 'PAID'
            else:
                self.status = 'PARTIALLY_PAID'

    def __str__(self):
        return self.ti_number


class TaxInvoiceItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tax_invoice = models.ForeignKey(TaxInvoice, on_delete=models.CASCADE, related_name='items')
    pi_item = models.ForeignKey(ProformaInvoiceItem, on_delete=models.SET_NULL, null=True, blank=True)

    description   = models.TextField(blank=True, default='')   # Product / Work description
    hs_sac_code   = models.CharField(max_length=50, blank=True, default='')  # H.S. Code or SAC Code
    quantity      = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit          = models.CharField(max_length=20, blank=True, default='No.')
    rate          = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    amount        = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    taxable_value = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    sgst_rate   = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    cgst_rate   = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    cgst_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    igst_rate   = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    igst_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    total_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    sort_order   = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'tax_invoice_items'
        ordering = ['sort_order']

    def save(self, *args, **kwargs):
        q = Decimal(str(self.quantity or 0))
        rate = Decimal(str(self.rate or 0))
        self.amount = q * rate
        if not self.taxable_value:
            self.taxable_value = self.amount
        tv = Decimal(str(self.taxable_value or 0))
        self.sgst_amount = tv * Decimal(str(self.sgst_rate or 0)) / 100
        self.cgst_amount = tv * Decimal(str(self.cgst_rate or 0)) / 100
        self.igst_amount = tv * Decimal(str(self.igst_rate or 0)) / 100
        self.total_amount = tv + self.sgst_amount + self.cgst_amount + self.igst_amount
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.tax_invoice.ti_number} - item"


class TaxInvoicePayment(models.Model):
    """Collections recorded against a Service Tax Invoice (Finance module)."""
    PAYMENT_MODE_CHOICES = [
        ('CASH',   'Cash'),
        ('CHEQUE', 'Cheque'),
        ('NEFT',   'NEFT'),
        ('RTGS',   'RTGS'),
        ('IMPS',   'IMPS'),
        ('UPI',    'UPI'),
        ('OTHER',  'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tax_invoice = models.ForeignKey(TaxInvoice, on_delete=models.CASCADE, related_name='payments')

    payment_number   = models.PositiveIntegerField()
    amount           = models.DecimalField(max_digits=16, decimal_places=2)
    payment_date     = models.DateField()
    payment_mode     = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES, default='NEFT')
    reference_number = models.CharField(max_length=100, blank=True, default='')
    remarks          = models.TextField(blank=True, default='')

    total_paid_after = models.DecimalField(max_digits=16, decimal_places=2)
    balance_after    = models.DecimalField(max_digits=16, decimal_places=2)

    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                    related_name='tax_invoice_payments_recorded')
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tax_invoice_payments'
        ordering = ['tax_invoice', 'payment_number']

    def __str__(self):
        return f"{self.tax_invoice.ti_number} – Payment #{self.payment_number} – {self.amount}"
