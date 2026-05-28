from django.db import models
from django.conf import settings
from inventory.models import Product
from sales.models import ProformaInvoice, ProformaInvoiceItem
from core.models import CURRENCY_CHOICES
import uuid
from decimal import Decimal
from datetime import datetime


# ═════════════════════════════════════════════════════════════════════════════
# PI Bill — Generated from Proforma Invoice (GST + Discount applied here)
# ═════════════════════════════════════════════════════════════════════════════

class PIBill(models.Model):
    BILL_TYPE_CHOICES = [
        ('DOMESTIC',      'Domestic'),
        ('INTERNATIONAL', 'International'),
    ]

    STATUS_CHOICES = [
        ('DRAFT',     'Draft'),
        ('GENERATED', 'Generated'),
        ('PAID',      'Paid'),
        ('CANCELLED', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bill_number = models.CharField(max_length=50, unique=True, editable=False)

    bill_type = models.CharField(max_length=15, choices=BILL_TYPE_CHOICES, default='DOMESTIC')
    proforma_invoice = models.ForeignKey(
        ProformaInvoice, on_delete=models.PROTECT, related_name='pi_bills',
    )

    bill_date = models.DateField()

    client_name    = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=100, blank=True)
    phone          = models.CharField(max_length=15, blank=True)
    email          = models.EmailField(blank=True)
    address        = models.TextField(blank=True)

    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='INR')
    conversion_rate = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True,
        help_text="INR conversion rate (immutable, copied from PI)"
    )

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    cgst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    sgst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    igst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    igst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    discount_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Discount subtracted from total"
    )

    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                       help_text="subtotal + GST - discount")
    net_payable = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    remarks = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='GENERATED')

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                    related_name='pi_bills_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'pi_bills'
        ordering = ['-bill_number']

    def save(self, *args, **kwargs):
        if not self.bill_number:
            year = datetime.now().year
            last = PIBill.objects.filter(
                bill_number__startswith=f'PIB/{year}/'
            ).order_by('-bill_number').first()
            new_num = int(last.bill_number.split('/')[-1]) + 1 if last else 1
            self.bill_number = f'PIB/{year}/{new_num:04d}'
        super().save(*args, **kwargs)

    def calculate_totals(self):
        self.subtotal = sum(item.amount for item in self.pi_bill_items.all())
        self.cgst_amount = (self.subtotal * self.cgst_percentage) / 100
        self.sgst_amount = (self.subtotal * self.sgst_percentage) / 100
        self.igst_amount = (self.subtotal * self.igst_percentage) / 100
        self.total_amount = (
            self.subtotal + self.cgst_amount + self.sgst_amount + self.igst_amount
            - self.discount_amount
        )
        self.net_payable = self.total_amount
        self.balance = self.net_payable - self.amount_paid
        self.save()

    def __str__(self):
        return f"{self.bill_number} - {self.client_name}"


class PIBillItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pi_bill = models.ForeignKey(PIBill, on_delete=models.CASCADE, related_name='pi_bill_items')
    pi_item = models.ForeignKey(ProformaInvoiceItem, on_delete=models.PROTECT, null=True, blank=True)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, null=True, blank=True)

    item_name   = models.CharField(max_length=200)
    hsn_code    = models.CharField(max_length=50, blank=True)
    unit        = models.CharField(max_length=20, default='PCS')
    quantity    = models.DecimalField(max_digits=10, decimal_places=2)
    rate        = models.DecimalField(max_digits=10, decimal_places=2)
    amount      = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        db_table = 'pi_bill_items'

    def save(self, *args, **kwargs):
        self.amount = Decimal(str(self.quantity)) * Decimal(str(self.rate))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.pi_bill.bill_number} - {self.item_name}"


class PIBillPayment(models.Model):
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

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    pi_bill = models.ForeignKey(
        PIBill, on_delete=models.CASCADE, related_name='payments',
    )

    payment_number = models.PositiveIntegerField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_date = models.DateField()
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES, default='NEFT')
    reference_number = models.CharField(max_length=100, blank=True)
    remarks = models.TextField(blank=True)

    total_paid_after = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='pi_bill_payments_recorded',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'pi_bill_payments'
        ordering = ['pi_bill', 'payment_number']

    def __str__(self):
        return f"{self.pi_bill.bill_number} – Payment #{self.payment_number} – {self.amount}"
