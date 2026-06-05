from django.db import models, transaction
from django.conf import settings
from inventory.models import Product
from vendors.models import Vendor
from requisitions.models import Requisition, VendorQuotationItem
from core.models import CURRENCY_CHOICES
import uuid
from decimal import Decimal
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
    subject      = models.CharField(max_length=255, blank=True, default='')
    project_name = models.CharField(max_length=255, blank=True, default='')
    bill_to      = models.TextField(blank=True, default='')
    ship_to      = models.TextField(blank=True, default='')
    terms_and_conditions = models.JSONField(default=list, blank=True, help_text="Array of terms & conditions")
    remarks      = models.TextField(blank=True)

    # ── Currency ──────────────────────────────────────────────────────────────
    currency = models.CharField(
        max_length=3, choices=CURRENCY_CHOICES, default='INR',
        help_text="Currency inherited from vendor quotation"
    )
    conversion_rate = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True,
        help_text="INR conversion rate at the time of PO creation (for record only, no conversion applied)"
    )

    # ── Amounts (in the PO's stated currency) ────────────────────────────────
    items_total  = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Sum of all line-item amounts (qty × rate)"
    )

    # ── GST ───────────────────────────────────────────────────────────────────
    cgst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    sgst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    igst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    igst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    discount_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Vendor discount amount (in PO currency), subtracted from total"
    )

    total_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="items_total + GST - discount"
    )

    payment_due_date = models.DateField(
        null=True, blank=True,
        help_text="Payment due date to vendor"
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

    # ── Revision tracking ────────────────────────────────────────────────────
    revision_number = models.PositiveIntegerField(
        default=0,
        help_text="Incremented on each edit; 0 = original"
    )
    is_revised = models.BooleanField(default=False)

    # ── Edit locking ─────────────────────────────────────────────────────────
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='locked_purchase_orders',
        help_text="User currently editing this PO"
    )
    locked_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Timestamp when PO was locked for editing"
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
            import re
            vendor_name = self.vendor.vendor_name.strip()
            vendor_prefix = re.split(r'\s+', vendor_name)[0].upper()
            prefix = f'EEL/IND/{vendor_prefix}'

            last_po = PurchaseOrder.objects.filter(
                po_number__startswith=prefix + '/'
            ).order_by('-created_at').first()

            if last_po:
                num_part = last_po.po_number.split('/')[-1]
                num_part = num_part.rstrip('R')
                new_num = int(num_part) + 1
            else:
                new_num = 100

            self.po_number = f'{prefix}/{new_num}'

        super().save(*args, **kwargs)

    def calculate_total(self):
        """Recalculate items_total, GST, total_amount, and balance."""
        self.items_total = sum(item.amount for item in self.items.all())

        self.cgst_amount = (self.items_total * self.cgst_percentage) / Decimal('100')
        self.sgst_amount = (self.items_total * self.sgst_percentage) / Decimal('100')
        self.igst_amount = (self.items_total * self.igst_percentage) / Decimal('100')

        self.total_amount = (
            self.items_total
            + self.cgst_amount
            + self.sgst_amount
            + self.igst_amount
            - self.discount_amount
        )
        self.balance = self.total_amount - self.amount_paid
        self.save()

    def update_status(self):
        """
        Recompute status from item receipts and persist using a targeted
        UPDATE (only touches the 'status' column — never overwrites
        amount_paid, balance, or any other field).

        FIX: Previously used self.save() which could overwrite stale
        in-memory values for balance/amount_paid back to the DB.
        """
        # Never change a cancelled PO's status
        if self.status == 'CANCELLED':
            return

        # Use DB counts — immune to any in-memory caching issues
        total_items    = self.items.count()
        received_items = self.items.filter(is_received=True).count()

        if total_items > 0 and total_items == received_items:
            new_status = 'COMPLETED'
        elif received_items > 0:
            new_status = 'PARTIALLY_RECEIVED'
        else:
            new_status = 'PENDING'

        # Targeted SQL: UPDATE purchase_orders SET status=? WHERE id=?
        # This guarantees no other column is touched.
        PurchaseOrder.objects.filter(pk=self.pk).update(status=new_status)

        # Keep the in-memory object consistent so callers get the right value
        # after this call without needing an extra refresh_from_db().
        self.status = new_status

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
                item.product.purchase_count = max(item.product.purchase_count - 1, 0)
                item.product.total_purchased_qty = max(item.product.total_purchased_qty - item.quantity, 0)
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
    quotation_item = models.ForeignKey(VendorQuotationItem, on_delete=models.PROTECT, null=True, blank=True)
    product        = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity       = models.DecimalField(max_digits=10, decimal_places=2)
    rate           = models.DecimalField(max_digits=10, decimal_places=2, help_text="Rate per unit")
    amount         = models.DecimalField(max_digits=12, decimal_places=2, help_text="quantity × rate")

    is_received    = models.BooleanField(default=False)

    class Meta:
        db_table = 'purchase_order_items'

    def save(self, *args, **kwargs):
        from decimal import Decimal
        self.amount = Decimal(str(self.quantity)) * Decimal(str(self.rate))
        super().save(*args, **kwargs)

    def mark_as_purchased(self):
        """
        Update stock when item is received.

        FIX: After saving the item and calling update_status(), we refresh
        self.po from DB so any caller holding this item's .po reference
        sees the final correct status immediately.
        """
        from datetime import date

        if self.po.status == 'CANCELLED':
            raise ValueError("Cannot receive items on a cancelled purchase order.")

        if not self.is_received:
            self.product.current_stock += self.quantity
            self.product.purchase_count += 1
            self.product.total_purchased_qty += self.quantity
            self.product.last_purchase_date = date.today()
            self.product.requisition_number = self.po.requisition.requisition_number
            self.product.save()

            self.is_received = True
            self.save()

            # update_status() now uses a targeted QuerySet.update()
            # so it only writes the status column — safe to call here.
            self.po.update_status()

    def __str__(self):
        return f"{self.po.po_number} - {self.product.item_name}"
