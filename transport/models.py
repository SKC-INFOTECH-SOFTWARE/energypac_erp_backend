from django.db import models
from django.conf import settings
from purchase_orders.models import PurchaseOrder
from sales.models import ProformaInvoice
import uuid
from decimal import Decimal


class Transporter(models.Model):
    """Transporter master — a reusable transporter/courier company with its own ledger."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transporter_code = models.CharField(max_length=30, unique=True, editable=False)
    name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    gst_number = models.CharField(max_length=30, blank=True)
    pan_number = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'transporters'
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.transporter_code:
            last = Transporter.objects.filter(
                transporter_code__startswith='TPR/'
            ).order_by('-transporter_code').first()
            if last:
                try:
                    new_num = int(last.transporter_code.split('/')[-1]) + 1
                except (ValueError, IndexError):
                    new_num = Transporter.objects.count() + 1
            else:
                new_num = 1
            self.transporter_code = f'TPR/{new_num:04d}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.transporter_code} - {self.name}"


class TransportEntry(models.Model):
    DISPATCH_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('IN_TRANSIT', 'In Transit'),
        ('DELIVERED', 'Delivered'),
        ('CANCELLED', 'Cancelled'),
    ]
    PAYMENT_STATUS_CHOICES = [
        ('UNPAID', 'Unpaid'),
        ('PARTIALLY_PAID', 'Partially Paid'),
        ('PAID', 'Paid'),
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
    transporter = models.ForeignKey(
        Transporter, on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='transport_entries',
    )
    transporter_name = models.CharField(max_length=200)
    transporter_contact = models.CharField(max_length=50, blank=True)
    vehicle_number = models.CharField(max_length=50, blank=True)
    driver_name = models.CharField(max_length=200, blank=True)
    driver_contact = models.CharField(max_length=50, blank=True)

    # Carrier document references (LR / consignment note)
    lr_number = models.CharField(max_length=100, blank=True, help_text="Lorry Receipt / Consignment note number")
    invoice_reference = models.CharField(max_length=100, blank=True, help_text="Transporter's invoice / bilty number")

    dispatch_date = models.DateField(null=True, blank=True)
    expected_delivery_date = models.DateField(null=True, blank=True)
    actual_delivery_date = models.DateField(null=True, blank=True)

    dispatch_from = models.CharField(max_length=300, blank=True)
    dispatch_to = models.CharField(max_length=300, blank=True)

    total_cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Auto-calculated sum of all cost items"
    )
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_status = models.CharField(
        max_length=20, choices=PAYMENT_STATUS_CHOICES, default='UNPAID'
    )

    status = models.CharField(max_length=20, choices=DISPATCH_STATUS_CHOICES, default='PENDING')
    remarks = models.TextField(blank=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'transport_entries'
        ordering = ['-created_at']

    @property
    def direction(self):
        """BUY = inbound freight on a Purchase Order; SELL = outbound freight on a Proforma Invoice."""
        if self.purchase_order_id:
            return 'BUY'
        if self.proforma_invoice_id:
            return 'SELL'
        return 'UNKNOWN'

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
        self.recalc_balance()
        self.save(update_fields=['total_cost', 'balance', 'payment_status'])

    def recalc_balance(self):
        """Recompute balance + payment_status from total_cost and amount_paid."""
        self.balance = (self.total_cost or Decimal('0')) - (self.amount_paid or Decimal('0'))
        if self.balance < 0:
            self.balance = Decimal('0')
        if self.status == 'CANCELLED':
            return
        if (self.amount_paid or Decimal('0')) <= 0:
            self.payment_status = 'UNPAID'
        elif self.balance <= 0:
            self.payment_status = 'PAID'
        else:
            self.payment_status = 'PARTIALLY_PAID'

    def __str__(self):
        ref = self.purchase_order.po_number if self.purchase_order else (
            self.proforma_invoice.pi_number if self.proforma_invoice else 'N/A'
        )
        return f"{self.transport_number} - {ref}"


class TransportConsignmentItem(models.Model):
    """
    Item-level tracking of what was actually shipped on a single transport entry —
    enables partial shipments (e.g. a PO of 10 units shipped 5 + 5 across two trips,
    or a PI of 15 units shipped 4 then 11).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transport_entry = models.ForeignKey(
        TransportEntry, on_delete=models.CASCADE, related_name='consignment_items'
    )
    po_item = models.ForeignKey(
        'purchase_orders.PurchaseOrderItem', on_delete=models.PROTECT,
        null=True, blank=True, related_name='consignment_items',
    )
    pi_item = models.ForeignKey(
        'sales.ProformaInvoiceItem', on_delete=models.PROTECT,
        null=True, blank=True, related_name='consignment_items',
    )
    product = models.ForeignKey('inventory.Product', on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    remarks = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = 'transport_consignment_items'

    def __str__(self):
        return f"{self.product.item_name} × {self.quantity}"


class TransportPayment(models.Model):
    """A payment made to (BUY side) or received against (SELL side) a transport entry."""
    PAYMENT_MODE_CHOICES = [
        ('CASH', 'Cash'),
        ('CHEQUE', 'Cheque'),
        ('NEFT', 'NEFT'),
        ('RTGS', 'RTGS'),
        ('IMPS', 'IMPS'),
        ('UPI', 'UPI'),
        ('TT', 'Telegraphic Transfer'),
        ('OTHER', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transport_entry = models.ForeignKey(
        TransportEntry, on_delete=models.CASCADE, related_name='payments'
    )
    payment_number = models.CharField(max_length=50, editable=False, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_date = models.DateField()
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES, default='NEFT')
    reference_number = models.CharField(max_length=100, blank=True)
    remarks = models.TextField(blank=True)

    total_paid_after = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='transport_payments_recorded',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'transport_payments'
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.payment_number:
            from datetime import datetime
            year = datetime.now().year
            last = TransportPayment.objects.filter(
                payment_number__startswith=f'TPAY/{year}/'
            ).order_by('-payment_number').first()
            if last:
                try:
                    new_num = int(last.payment_number.split('/')[-1]) + 1
                except (ValueError, IndexError):
                    new_num = TransportPayment.objects.count() + 1
            else:
                new_num = 1
            self.payment_number = f'TPAY/{year}/{new_num:04d}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.payment_number} - {self.amount}"


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
