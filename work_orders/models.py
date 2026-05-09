from django.db import models
from django.conf import settings
from sales.models import SalesQuotation, SalesQuotationItem
from inventory.models import Product
from core.models import CURRENCY_CHOICES
import uuid
from datetime import datetime
from decimal import Decimal


class WorkOrder(models.Model):
    """
    Work Order - Generated from Sales Quotation
    One quotation → One work order (OneToOne relationship)
    """

    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('PARTIALLY_DELIVERED', 'Partially Delivered'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    wo_number = models.CharField(
        max_length=50,
        unique=True,
        help_text="Auto-generated: WO/YEAR/NUMBER or manual input"
    )

    # OneToOne relationship with SalesQuotation
    sales_quotation = models.OneToOneField(
        SalesQuotation,
        on_delete=models.PROTECT,
        related_name='work_order',
        help_text="Reference sales quotation (one WO per quotation)"
    )

    wo_date = models.DateField(help_text="Work order date")

    # ── Currency (inherited from Sales Quotation) ─────────────────────────
    currency = models.CharField(
        max_length=3, choices=CURRENCY_CHOICES, default='INR',
        help_text="Currency inherited from sales quotation"
    )
    exchange_rate = models.DecimalField(
        max_digits=10, decimal_places=4, default=1,
        help_text="USD to INR rate (1 if INR)"
    )

    # Client details (copied from quotation)
    client_name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=15, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)

    # Financial details
    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Sum of all items before tax"
    )

    cgst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    sgst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    igst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    igst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Subtotal + all taxes (INR)"
    )

    # ── Original currency amounts ────────────────────────────────────────
    original_subtotal = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Subtotal in original currency"
    )
    original_cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    original_sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    original_igst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    original_total_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Total in original currency"
    )

    # Advance payment tracking
    advance_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Total advance received"
    )

    advance_deducted = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Total advance deducted across all bills"
    )

    advance_remaining = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Remaining advance (auto-calculated)"
    )

    # Delivery tracking
    total_delivered_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Total value delivered across all bills"
    )

    remarks = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'work_orders'
        ordering = ['-wo_number']
        verbose_name = 'Work Order'
        verbose_name_plural = 'Work Orders'

    def save(self, *args, **kwargs):
        # Calculate advance remaining
        self.advance_remaining = self.advance_amount - self.advance_deducted

        # Auto-generate WO number if not provided
        if not self.wo_number:
            year = datetime.now().year
            last_wo = WorkOrder.objects.filter(
                wo_number__startswith=f'WO/{year}/'
            ).order_by('-wo_number').first()

            new_num = int(last_wo.wo_number.split('/')[-1]) + 1 if last_wo else 1
            self.wo_number = f'WO/{year}/{new_num:04d}'

        super().save(*args, **kwargs)

    def update_status(self):
        """Update status based on delivery completion"""
        items = self.items.all()

        if not items:
            return

        total_pending = sum(item.pending_quantity for item in items)

        if total_pending == 0:
            # All items fully delivered
            self.status = 'COMPLETED'
        elif any(item.delivered_quantity > 0 for item in items):
            # Some items delivered
            self.status = 'PARTIALLY_DELIVERED'
        else:
            # No deliveries yet
            self.status = 'ACTIVE'

        self.save()

    def __str__(self):
        return f"{self.wo_number} - {self.client_name}"


class WorkOrderItem(models.Model):
    """
    Work Order Items - Items from quotation with stock tracking
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    work_order = models.ForeignKey(
        WorkOrder,
        on_delete=models.CASCADE,
        related_name='items'
    )

    # Product reference (may be null for manual entries)
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        null=True,
        blank=True
    )

    # Item details (editable during WO creation)
    item_code = models.CharField(max_length=50)
    item_name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    hsn_code = models.CharField(max_length=20, blank=True)
    unit = models.CharField(max_length=20, default='PCS')

    # Quantities
    ordered_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Total quantity ordered"
    )

    delivered_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Total quantity delivered across all bills"
    )

    pending_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Remaining quantity (auto-calculated)"
    )

    # Pricing (editable during WO creation)
    rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Rate per unit (INR)"
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="ordered_quantity × rate (INR)"
    )

    # ── Original currency amounts ────────────────────────────────────────
    original_rate = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Rate in original currency"
    )
    original_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Amount in original currency"
    )

    # Stock status (snapshot at WO creation time)
    stock_available = models.BooleanField(
        default=False,
        help_text="Stock availability at WO creation"
    )

    stock_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Stock quantity at WO creation"
    )

    remarks = models.TextField(blank=True)

    class Meta:
        db_table = 'work_order_items'
        verbose_name = 'Work Order Item'
        verbose_name_plural = 'Work Order Items'

    def save(self, *args, **kwargs):
        self.amount = self.ordered_quantity * self.rate
        self.pending_quantity = self.ordered_quantity - self.delivered_quantity

        currency = self.work_order.currency
        if currency == 'USD' and self.work_order.exchange_rate:
            self.original_rate = self.original_rate or (self.rate / self.work_order.exchange_rate)
            self.original_amount = self.ordered_quantity * self.original_rate
        else:
            self.original_rate = self.rate
            self.original_amount = self.amount

        if self.product:
            current_stock = self.product.current_stock
            self.stock_available = current_stock >= self.ordered_quantity
            self.stock_quantity = current_stock

        super().save(*args, **kwargs)

    def get_stock_status(self):
        """Get current stock status (for billing)"""
        if not self.product:
            return {
                'status': 'MANUAL_ITEM',
                'message': 'Manual entry - no stock tracking',
                'current_stock': 0
            }

        current_stock = self.product.current_stock
        pending = self.pending_quantity

        if current_stock >= pending:
            return {
                'status': 'IN_STOCK',
                'message': f'In Stock',
                'current_stock': float(current_stock),
                'pending': float(pending)
            }
        elif current_stock > 0:
            return {
                'status': 'PARTIAL_STOCK',
                'message': f'Partial Stock',
                'current_stock': float(current_stock),
                'pending': float(pending)
            }
        else:
            return {
                'status': 'OUT_OF_STOCK',
                'message': 'Out of Stock',
                'current_stock': 0,
                'pending': float(pending)
            }

    def __str__(self):
        return f"{self.work_order.wo_number} - {self.item_name}"
