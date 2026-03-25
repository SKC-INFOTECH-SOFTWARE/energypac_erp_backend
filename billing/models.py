from django.db import models
from django.conf import settings
from work_orders.models import WorkOrder, WorkOrderItem
from inventory.models import Product
import uuid
from datetime import datetime
from django.db import transaction


class Bill(models.Model):
    """
    Bill/Invoice - Generated from Work Order

    Bill Types
    ----------
    DOMESTIC     : Standard GST bill for domestic clients (CGST+SGST or IGST).
    INTERNATIONAL: Export invoice for foreign clients. GST can be set to 0%
                   for zero-rated exports. All amounts are always in INR.

    Freight Cost
    ------------
    freight_cost is a flat charge added AFTER tax but BEFORE advance deduction:
        net_payable = total_amount + freight_cost - advance_deducted

    Export Fields (optional — mainly for INTERNATIONAL bills)
    ---------------------------------------------------------
    importer_address, port_of_loading, port_of_discharge, final_destination,
    pre_carriage_by, terms_of_delivery_payment, vessel_flight_no
    """

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

    bill_number = models.CharField(
        max_length=50,
        unique=True,
        editable=False,
        help_text="Auto-generated: BILL/YEAR/NUMBER"
    )

    # ── Bill type ─────────────────────────────────────────────────────────────
    bill_type = models.CharField(
        max_length=15,
        choices=BILL_TYPE_CHOICES,
        default='DOMESTIC',
        help_text="Domestic or International (classification only; all amounts in INR)"
    )

    work_order = models.ForeignKey(
        WorkOrder,
        on_delete=models.PROTECT,
        related_name='bills',
        help_text="Reference work order"
    )

    bill_date = models.DateField(help_text="Bill generation date")

    # Client details (copied from WO)
    client_name    = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=100, blank=True)
    phone          = models.CharField(max_length=15, blank=True)
    email          = models.EmailField(blank=True)
    address        = models.TextField(blank=True)

    # ── Export / International shipping fields (all optional) ─────────────────
    importer_address = models.TextField(
        blank=True,
        help_text="Importer's address (for international / export bills)"
    )
    port_of_loading = models.CharField(
        max_length=200, blank=True,
        help_text="Port of loading"
    )
    port_of_discharge = models.CharField(
        max_length=200, blank=True,
        help_text="Port of discharge"
    )
    final_destination = models.CharField(
        max_length=200, blank=True,
        help_text="Final destination"
    )
    pre_carriage_by = models.CharField(
        max_length=200, blank=True,
        help_text="Pre-carriage by (mode of transport to loading port)"
    )
    terms_of_delivery_payment = models.CharField(
        max_length=200, blank=True,
        help_text="Terms of delivery/payment (e.g. CIF, FOB, DAP, EXW)"
    )
    vessel_flight_no = models.CharField(
        max_length=100, blank=True,
        help_text="Vessel name / flight number"
    )

    # ── Financial amounts (always stored in INR) ──────────────────────────────
    subtotal = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Sum of delivered items before tax (INR)"
    )

    cgst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    sgst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    igst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    igst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    total_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Subtotal + all taxes (INR)"
    )

    # ── Freight ───────────────────────────────────────────────────────────────
    freight_cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Flat freight / shipping charge added after tax (INR)"
    )

    # ── Advance deduction ─────────────────────────────────────────────────────
    advance_deducted = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Advance amount deducted in this bill (INR)"
    )

    net_payable = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="total_amount + freight_cost - advance_deducted (INR)"
    )

    # ── Payment tracking ──────────────────────────────────────────────────────
    amount_paid = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Total amount paid by client (sum of all BillPayment rows, INR)"
    )

    balance = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Remaining balance (net_payable - amount_paid, INR)"
    )

    remarks = models.TextField(blank=True)

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='GENERATED'
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'bills'
        ordering = ['-bill_number']
        verbose_name = 'Bill'
        verbose_name_plural = 'Bills'

    # ── save ──────────────────────────────────────────────────────────────────

    def save(self, *args, **kwargs):
        if not self.bill_number:
            year = datetime.now().year
            last_bill = Bill.objects.filter(
                bill_number__startswith=f'BILL/{year}/'
            ).order_by('-bill_number').first()

            new_num = int(last_bill.bill_number.split('/')[-1]) + 1 if last_bill else 1
            self.bill_number = f'BILL/{year}/{new_num:04d}'

        super().save(*args, **kwargs)

    # ── calculate_totals ──────────────────────────────────────────────────────

    def calculate_totals(self):
        """
        Recalculate all amounts.

        Formula
        -------
        subtotal      = sum(item.amount)
        cgst_amount   = subtotal × cgst_percentage / 100
        sgst_amount   = subtotal × sgst_percentage / 100
        igst_amount   = subtotal × igst_percentage / 100
        total_amount  = subtotal + cgst + sgst + igst
        net_payable   = total_amount + freight_cost - advance_deducted
        balance       = net_payable - amount_paid
        """
        self.subtotal = sum(item.amount for item in self.items.all())

        wo = self.work_order
        self.cgst_percentage = wo.cgst_percentage
        self.sgst_percentage = wo.sgst_percentage
        self.igst_percentage = wo.igst_percentage

        self.cgst_amount = (self.subtotal * self.cgst_percentage) / 100
        self.sgst_amount = (self.subtotal * self.sgst_percentage) / 100
        self.igst_amount = (self.subtotal * self.igst_percentage) / 100

        self.total_amount = (
            self.subtotal +
            self.cgst_amount +
            self.sgst_amount +
            self.igst_amount
        )

        available_advance    = wo.advance_remaining
        self.advance_deducted = min(self.total_amount + self.freight_cost, available_advance)
        self.net_payable     = self.total_amount + self.freight_cost - self.advance_deducted
        self.balance         = self.net_payable - self.amount_paid

        self.save()

    def update_work_order_advance(self):
        """Update work order advance after bill generation."""
        wo = self.work_order
        wo.advance_deducted      += self.advance_deducted
        wo.total_delivered_value += self.total_amount
        wo.save()

    @transaction.atomic
    def deduct_stock(self):
        """Deduct stock for all delivered items."""
        for bill_item in self.items.all():
            if bill_item.product:
                product = bill_item.product
                product.current_stock -= bill_item.delivered_quantity
                product.save()

                wo_item = bill_item.work_order_item
                wo_item.delivered_quantity += bill_item.delivered_quantity
                wo_item.save()

        self.work_order.update_status()

    @transaction.atomic
    def restore_stock(self):
        """Restore stock if bill is cancelled."""
        for bill_item in self.items.all():
            if bill_item.product:
                product = bill_item.product
                product.current_stock += bill_item.delivered_quantity
                product.save()

                wo_item = bill_item.work_order_item
                wo_item.delivered_quantity -= bill_item.delivered_quantity
                wo_item.save()

        wo = self.work_order
        wo.advance_deducted      -= self.advance_deducted
        wo.total_delivered_value -= self.total_amount
        wo.save()

        wo.update_status()

    def __str__(self):
        return f"{self.bill_number} - {self.client_name}"


# ─────────────────────────────────────────────────────────────────────────────

class BillItem(models.Model):
    """Bill Items - Items delivered in this bill."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name='items')
    work_order_item = models.ForeignKey(WorkOrderItem, on_delete=models.PROTECT,
                                        help_text="Reference to work order item")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, null=True, blank=True)

    item_code   = models.CharField(max_length=50)
    item_name   = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    hsn_code    = models.CharField(max_length=20, blank=True)
    unit        = models.CharField(max_length=20, default='PCS')

    ordered_quantity = models.DecimalField(max_digits=10, decimal_places=2,
                                           help_text="Total quantity in work order")
    previously_delivered_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                                        help_text="Quantity delivered in previous bills")
    delivered_quantity = models.DecimalField(max_digits=10, decimal_places=2,
                                             help_text="Quantity delivered in THIS bill")
    pending_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                           help_text="Remaining quantity after this bill")

    rate   = models.DecimalField(max_digits=10, decimal_places=2, help_text="Rate per unit (INR)")
    amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="delivered_quantity × rate (INR)")

    remarks = models.TextField(blank=True)

    class Meta:
        db_table = 'bill_items'
        verbose_name = 'Bill Item'
        verbose_name_plural = 'Bill Items'

    def save(self, *args, **kwargs):
        wo_item = self.work_order_item
        self.product      = wo_item.product
        self.item_code    = wo_item.item_code
        self.item_name    = wo_item.item_name
        self.description  = wo_item.description
        self.hsn_code     = wo_item.hsn_code
        self.unit         = wo_item.unit
        self.rate         = wo_item.rate
        self.ordered_quantity              = wo_item.ordered_quantity
        self.previously_delivered_quantity = wo_item.delivered_quantity

        self.amount           = self.delivered_quantity * self.rate
        total_delivered       = self.previously_delivered_quantity + self.delivered_quantity
        self.pending_quantity = self.ordered_quantity - total_delivered

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.bill.bill_number} - {self.item_name}"


# ─────────────────────────────────────────────────────────────────────────────

class BillPayment(models.Model):
    """Individual payment transaction for a bill."""

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

    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name='payments',
                              help_text="Bill this payment belongs to")

    payment_number = models.PositiveIntegerField(
        help_text="Sequential payment number for this bill"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2,
                                  help_text="Amount paid in this transaction (INR)")
    payment_date  = models.DateField(help_text="Date on which payment was received")
    payment_mode  = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES, default='CASH')
    reference_number = models.CharField(max_length=100, blank=True,
                                        help_text="Cheque number / UTR / SWIFT reference")
    remarks = models.TextField(blank=True)

    # Running-total snapshot
    total_paid_after = models.DecimalField(max_digits=12, decimal_places=2,
                                            help_text="Cumulative amount_paid AFTER this transaction (INR)")
    balance_after    = models.DecimalField(max_digits=12, decimal_places=2,
                                            help_text="Remaining balance AFTER this transaction (INR)")

    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table      = 'bill_payments'
        ordering      = ['bill', 'payment_number']
        verbose_name  = 'Bill Payment'
        verbose_name_plural = 'Bill Payments'

    def __str__(self):
        return f"{self.bill.bill_number} – Payment #{self.payment_number} – ₹{self.amount}"
