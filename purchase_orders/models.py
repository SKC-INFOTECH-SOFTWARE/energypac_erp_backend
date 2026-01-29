from django.db import models
from django.conf import settings
from inventory.models import Product
from vendors.models import Vendor
from requisitions.models import Requisition, VendorQuotationItem
import uuid
from datetime import datetime

class PurchaseOrder(models.Model):
    """Purchase Order - Simple, no tax"""

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PARTIALLY_RECEIVED', 'Partially Received'),
        ('COMPLETED', 'Completed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    po_number = models.CharField(max_length=50, unique=True, editable=False)
    requisition = models.ForeignKey(Requisition, on_delete=models.PROTECT)
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT)
    po_date = models.DateField()
    remarks = models.TextField(blank=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'purchase_orders'
        ordering = ['-po_number']

    def save(self, *args, **kwargs):
        if not self.po_number:
            year = datetime.now().year
            last_po = PurchaseOrder.objects.filter(
                po_number__startswith=f'PO/{year}/'
            ).order_by('-po_number').first()

            new_num = int(last_po.po_number.split('/')[-1]) + 1 if last_po else 1
            self.po_number = f'PO/{year}/{new_num:04d}'

        super().save(*args, **kwargs)

    def calculate_total(self):
        self.total_amount = sum(item.amount for item in self.items.all())
        self.save()

    def update_status(self):
        items = self.items.all()
        if all(item.is_received for item in items):
            self.status = 'COMPLETED'
        elif any(item.is_received for item in items):
            self.status = 'PARTIALLY_RECEIVED'
        self.save()

    def __str__(self):
        return f"{self.po_number} - {self.vendor.vendor_name}"


class PurchaseOrderItem(models.Model):
    """PO Items"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    po = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='items')
    quotation_item = models.ForeignKey(VendorQuotationItem, on_delete=models.PROTECT)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    rate = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    is_received = models.BooleanField(default=False)

    class Meta:
        db_table = 'purchase_order_items'

    def save(self, *args, **kwargs):
        self.amount = self.quantity * self.rate
        super().save(*args, **kwargs)

    def mark_as_purchased(self):
        """Update stock when purchased"""
        if not self.is_received:
            self.product.current_stock += self.quantity
            self.product.save()

            self.is_received = True
            self.save()

            self.po.update_status()

    def __str__(self):
        return f"{self.po.po_number} - {self.product.item_name}"
