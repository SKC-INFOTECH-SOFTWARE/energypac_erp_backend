from django.db import models
from django.conf import settings
from purchase_orders.models import PurchaseOrder
from sales.models import ProformaInvoice
import uuid
from decimal import Decimal


class TransportEntry(models.Model):
    DISPATCH_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('IN_TRANSIT', 'In Transit'),
        ('DELIVERED', 'Delivered'),
        ('CANCELLED', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transport_number = models.CharField(max_length=50, unique=True, editable=False)
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='transport_entries',
    )
    proforma_invoice = models.ForeignKey(
        ProformaInvoice, on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='transport_entries',
    )
    transporter_name = models.CharField(max_length=200)
    transporter_contact = models.CharField(max_length=50, blank=True)
    vehicle_number = models.CharField(max_length=50, blank=True)
    driver_name = models.CharField(max_length=200, blank=True)
    driver_contact = models.CharField(max_length=50, blank=True)

    dispatch_date = models.DateField(null=True, blank=True)
    expected_delivery_date = models.DateField(null=True, blank=True)
    actual_delivery_date = models.DateField(null=True, blank=True)

    dispatch_from = models.CharField(max_length=300, blank=True)
    dispatch_to = models.CharField(max_length=300, blank=True)

    total_cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Auto-calculated sum of all cost items"
    )
    status = models.CharField(max_length=20, choices=DISPATCH_STATUS_CHOICES, default='PENDING')
    remarks = models.TextField(blank=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'transport_entries'
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.transport_number:
            from datetime import datetime
            year = datetime.now().year
            last = TransportEntry.objects.filter(
                transport_number__startswith=f'TRN/{year}/'
            ).order_by('-transport_number').first()
            if last:
                last_num = int(last.transport_number.split('/')[-1])
                new_num = last_num + 1
            else:
                new_num = 1
            self.transport_number = f'TRN/{year}/{new_num:04d}'
        super().save(*args, **kwargs)

    def calculate_total(self):
        self.total_cost = sum(item.amount for item in self.cost_items.all())
        self.save(update_fields=['total_cost'])

    def __str__(self):
        ref = self.purchase_order.po_number if self.purchase_order else (
            self.proforma_invoice.pi_number if self.proforma_invoice else 'N/A'
        )
        return f"{self.transport_number} - {ref}"


class TransportCostItem(models.Model):
    COST_TYPE_CHOICES = [
        ('FREIGHT', 'Freight Charges'),
        ('LOADING', 'Loading Charges'),
        ('UNLOADING', 'Unloading Charges'),
        ('INSURANCE', 'Insurance'),
        ('CUSTOMS', 'Customs Duty'),
        ('OCTROI', 'Octroi / Entry Tax'),
        ('HANDLING', 'Handling Charges'),
        ('PACKAGING', 'Packaging Charges'),
        ('TOLL', 'Toll Charges'),
        ('OTHER', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transport_entry = models.ForeignKey(
        TransportEntry, on_delete=models.CASCADE, related_name='cost_items'
    )
    cost_type = models.CharField(max_length=20, choices=COST_TYPE_CHOICES)
    description = models.CharField(max_length=300, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    remarks = models.TextField(blank=True)

    class Meta:
        db_table = 'transport_cost_items'

    def __str__(self):
        return f"{self.get_cost_type_display()} - {self.amount}"
