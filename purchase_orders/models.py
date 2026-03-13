from django.db import models, transaction
from django.conf import settings
from inventory.models import Product
from vendors.models import Vendor
from requisitions.models import Requisition, VendorQuotationItem
import uuid
from datetime import datetime


class PurchaseOrder(models.Model):
    """Purchase Order - with optional freight cost"""

    STATUS_CHOICES = [
        ('PENDING',            'Pending'),
        ('PARTIALLY_RECEIVED', 'Partially Received'),
        ('COMPLETED',          'Completed'),
        ('CANCELLED',          'Cancelled'),
    ]

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    po_number    = models.CharField(max_length=50, unique=True, editable=False)
    requisition  = models.ForeignKey(Requisition, on_delete=models.PROTECT)
    vendor       = models.ForeignKey(Vendor, on_delete=models.PROTECT)
    po_date      = models.DateField()
    remarks      = models.TextField(blank=True)

    # ── Amounts ───────────────────────────────────────────────────────────────
    items_total  = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Sum of all line-item amounts (qty × rate)"
    )
    freight_cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Freight / shipping cost added on top of item total"
    )
    total_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="items_total + freight_cost"
    )

    # ── Payment tracking ──────────────────────────────────────────────────────
    amount_paid = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Total amount paid to vendor (sum of all PurchasePayment rows, INR)"
    )
    balance = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Remaining balance (total_amount - amount_paid, INR)"
    )

    status       = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    created_by   = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    # Cancellation audit
    cancellation_reason = models.TextField(
        blank=True,
        help_text="Reason for cancellation (filled by cancel API)"
    )
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='cancelled_purchase_orders',
        help_text="User who cancelled this PO"
    )
    cancelled_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Timestamp when PO was cancelled"
    )

    class Meta:
        db_table = 'purchase_orders'
        ordering = ['-po_number']

    def save(self, *args, **kwargs):
        if not self.po_number:
            year    = datetime.now().year
            last_po = PurchaseOrder.objects.filter(
                po_number__startswith=f'PO/{year}/'
            ).order_by('-po_number').first()

            new_num        = int(last_po.po_number.split('/')[-1]) + 1 if last_po else 1
            self.po_number = f'PO/{year}/{new_num:04d}'

        super().save(*args, **kwargs)

    def calculate_total(self):
        """Recalculate items_total, total_amount, and balance."""
        self.items_total = sum(item.amount for item in self.items.all())
        self.total_amount = self.items_total + self.freight_cost
        self.balance = self.total_amount - self.amount_paid
        self.save()

    def update_status(self):
        """Recompute status from item receipts (skip if already CANCELLED)."""
        if self.status == 'CANCELLED':
            return

        items = self.items.all()
        if all(item.is_received for item in items):
            self.status = 'COMPLETED'
        elif any(item.is_received for item in items):
            self.status = 'PARTIALLY_RECEIVED'
        else:
            self.status = 'PENDING'
        self.save()

    @transaction.atomic
    def cancel(self, cancelled_by_user, reason=''):
        from django.utils import timezone

        if self.status == 'CANCELLED':
            raise ValueError("Purchase order is already cancelled.")

        if self.status == 'COMPLETED':
            raise ValueError(
                "Cannot cancel a completed purchase order. "
                "All items have been received into stock."
            )

        reversed_items = []
        for item in self.items.all():
            if item.is_received:
                item.product.current_stock -= item.quantity
                item.product.save()

                item.is_received = False
                item.save()

                reversed_items.append({
                    'item_id':      str(item.id),
                    'product_code': item.product.item_code,
                    'product_name': item.product.item_name,
                    'quantity':     float(item.quantity),
                })

        self.status              = 'CANCELLED'
        self.cancellation_reason = reason
        self.cancelled_by        = cancelled_by_user
        self.cancelled_at        = timezone.now()
        self.save()

        return reversed_items

    def __str__(self):
        return f"{self.po_number} - {self.vendor.vendor_name}"


class PurchaseOrderItem(models.Model):
    """PO Items"""

    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    po             = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='items')
    quotation_item = models.ForeignKey(VendorQuotationItem, on_delete=models.PROTECT)
    product        = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity       = models.DecimalField(max_digits=10, decimal_places=2)
    rate           = models.DecimalField(max_digits=10, decimal_places=2)
    amount         = models.DecimalField(max_digits=12, decimal_places=2)
    is_received    = models.BooleanField(default=False)

    class Meta:
        db_table = 'purchase_order_items'

    def save(self, *args, **kwargs):
        self.amount = self.quantity * self.rate
        super().save(*args, **kwargs)

    def mark_as_purchased(self):
        """Update stock when item is received — blocked if PO is cancelled."""
        if self.po.status == 'CANCELLED':
            raise ValueError("Cannot receive items on a cancelled purchase order.")

        if not self.is_received:
            self.product.current_stock += self.quantity
            self.product.save()

            self.is_received = True
            self.save()

            self.po.update_status()

    def __str__(self):
        return f"{self.po.po_number} - {self.product.item_name}"
