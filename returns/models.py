from django.db import models
from django.conf import settings
from inventory.models import Product
from sales.models import ProformaInvoice
from purchase_orders.models import PurchaseOrder
import uuid
from decimal import Decimal
from datetime import datetime


RETURN_REASON_CHOICES = [
    ('DEFECTIVE', 'Defective'),
    ('WRONG_ITEM', 'Wrong Item'),
    ('EXCESS', 'Excess Quantity'),
    ('DAMAGED', 'Damaged in Transit'),
    ('QUALITY', 'Quality Issue'),
    ('OTHER', 'Other'),
]

ITEM_CONDITION_CHOICES = [
    ('GOOD', 'Good — Resalable'),
    ('DAMAGED', 'Damaged — Needs Repair'),
    ('UNUSABLE', 'Unusable — Write Off'),
]


class SalesReturn(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('APPROVED', 'Approved'),
        ('CANCELLED', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    return_number = models.CharField(max_length=50, unique=True, editable=False)
    proforma_invoice = models.ForeignKey(
        ProformaInvoice, on_delete=models.PROTECT, related_name='sales_returns'
    )
    return_date = models.DateField()
    reason = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')

    credit_note_number = models.CharField(max_length=50, blank=True, default='')
    total_return_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    currency = models.CharField(max_length=10, default='INR')
    conversion_rate = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal('1'))

    notes = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='sales_returns_created')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='sales_returns_approved')
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sales_returns'
        ordering = ['-return_number']

    def save(self, *args, **kwargs):
        if not self.return_number:
            year = datetime.now().year
            prefix = f'EEL/SR/{year}'
            last = SalesReturn.objects.filter(
                return_number__startswith=prefix + '/'
            ).order_by('-created_at').first()
            new_num = 1
            if last:
                try:
                    new_num = int(last.return_number.split('/')[-1]) + 1
                except ValueError:
                    pass
            self.return_number = f'{prefix}/{new_num:04d}'

        if not self.currency:
            self.currency = self.proforma_invoice.currency
        if self.conversion_rate == Decimal('1') and self.proforma_invoice.conversion_rate:
            self.conversion_rate = self.proforma_invoice.conversion_rate

        super().save(*args, **kwargs)

    def calculate_total(self):
        self.total_return_amount = sum(item.amount for item in self.items.all())
        self.save()

    def __str__(self):
        return f"{self.return_number} ({self.proforma_invoice.pi_number})"


class SalesReturnItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sales_return = models.ForeignKey(SalesReturn, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.CharField(max_length=20, choices=RETURN_REASON_CHOICES, default='OTHER')
    condition = models.CharField(max_length=20, choices=ITEM_CONDITION_CHOICES, default='GOOD')
    notes = models.TextField(blank=True, default='')

    @property
    def amount(self):
        return self.quantity * self.unit_price

    class Meta:
        db_table = 'sales_return_items'

    def __str__(self):
        return f"{self.product.item_name} x {self.quantity}"


class PurchaseReturn(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('APPROVED', 'Approved'),
        ('CANCELLED', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    return_number = models.CharField(max_length=50, unique=True, editable=False)
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.PROTECT, related_name='purchase_returns'
    )
    return_date = models.DateField()
    reason = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')

    debit_note_number = models.CharField(max_length=50, blank=True, default='')
    total_return_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    currency = models.CharField(max_length=10, default='INR')
    conversion_rate = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal('1'))

    notes = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='purchase_returns_created')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='purchase_returns_approved')
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'purchase_returns'
        ordering = ['-return_number']

    def save(self, *args, **kwargs):
        if not self.return_number:
            year = datetime.now().year
            prefix = f'EEL/PR/{year}'
            last = PurchaseReturn.objects.filter(
                return_number__startswith=prefix + '/'
            ).order_by('-created_at').first()
            new_num = 1
            if last:
                try:
                    new_num = int(last.return_number.split('/')[-1]) + 1
                except ValueError:
                    pass
            self.return_number = f'{prefix}/{new_num:04d}'

        if not self.currency:
            self.currency = self.purchase_order.currency
        if self.conversion_rate == Decimal('1') and self.purchase_order.conversion_rate:
            self.conversion_rate = self.purchase_order.conversion_rate

        super().save(*args, **kwargs)

    def calculate_total(self):
        self.total_return_amount = sum(item.amount for item in self.items.all())
        self.save()

    def __str__(self):
        return f"{self.return_number} ({self.purchase_order.po_number})"


class PurchaseReturnItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase_return = models.ForeignKey(PurchaseReturn, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.CharField(max_length=20, choices=RETURN_REASON_CHOICES, default='OTHER')
    condition = models.CharField(max_length=20, choices=ITEM_CONDITION_CHOICES, default='GOOD')
    notes = models.TextField(blank=True, default='')

    @property
    def amount(self):
        return self.quantity * self.unit_price

    class Meta:
        db_table = 'purchase_return_items'

    def __str__(self):
        return f"{self.product.item_name} x {self.quantity}"
