from django.db import models
from django.conf import settings
from inventory.models import Product
from vendors.models import Vendor
from core.models import CURRENCY_CHOICES
import uuid
from decimal import Decimal
from datetime import datetime

class Requisition(models.Model):
    """Requisition/Purchase Request"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requisition_number = models.CharField(max_length=50, unique=True,
                                          help_text="Manual entry or auto-generated: EEL/YEAR/NUMBER")
    requisition_date = models.DateField(help_text="Date of requisition")
    remarks = models.TextField(blank=True, help_text="Additional notes")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                    related_name='requisitions_created',
                                    help_text="User who created this requisition")
    is_assigned = models.BooleanField(default=False,
                                      help_text="Whether vendors are assigned")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'requisitions'
        ordering = ['-requisition_number']
        verbose_name = 'Requisition'
        verbose_name_plural = 'Requisitions'

    def save(self, *args, **kwargs):
        if not self.requisition_number:
            # Generate: EEL/2026/001
            year = datetime.now().year
            last_req = Requisition.objects.filter(
                requisition_number__startswith=f'EEL/{year}/'
            ).order_by('-requisition_number').first()

            if last_req:
                last_num = int(last_req.requisition_number.split('/')[-1])
                new_num = last_num + 1
            else:
                new_num = 1

            self.requisition_number = f'EEL/{year}/{new_num:03d}'

        super().save(*args, **kwargs)

    def __str__(self):
        return self.requisition_number


class RequisitionItem(models.Model):
    """Items in a requisition"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requisition = models.ForeignKey(Requisition, on_delete=models.CASCADE,
                                     related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=10, decimal_places=2,
                                   help_text="Required quantity")
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'requisition_items'
        verbose_name = 'Requisition Item'
        verbose_name_plural = 'Requisition Items'

    def __str__(self):
        return f"{self.requisition.requisition_number} - {self.product.item_name}"


class VendorRequisitionAssignment(models.Model):
    """Vendor assignment to requisition"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requisition = models.ForeignKey(Requisition, on_delete=models.PROTECT,
                                     help_text="Reference requisition")
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT,
                               help_text="Assigned vendor")
    assignment_date = models.DateField(auto_now_add=True)
    remarks = models.TextField(blank=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                     help_text="User who made the assignment")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'vendor_requisition_assignments'
        ordering = ['-created_at']
        verbose_name = 'Vendor Assignment'
        verbose_name_plural = 'Vendor Assignments'
        constraints = [
            models.UniqueConstraint(
                fields=['requisition', 'vendor'],
                name='unique_vendor_per_requisition'
            )
        ]

    def __str__(self):
        return f"{self.requisition.requisition_number} - {self.vendor.vendor_name}"


class VendorRequisitionItem(models.Model):
    """Items assigned to vendor"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assignment = models.ForeignKey(VendorRequisitionAssignment, on_delete=models.CASCADE,
                                    related_name='items')
    requisition_item = models.ForeignKey(RequisitionItem, on_delete=models.PROTECT)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'vendor_requisition_items'
        verbose_name = 'Vendor Item'
        verbose_name_plural = 'Vendor Items'

    def __str__(self):
        return f"{self.assignment} - {self.product.item_name}"


class VendorQuotation(models.Model):
    """Vendor Quotation for assigned requisition"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assignment = models.ForeignKey(
        VendorRequisitionAssignment,
        on_delete=models.PROTECT,
        related_name='quotations',
        help_text="Reference to vendor assignment"
    )
    quotation_number = models.CharField(
        max_length=50,
        unique=True,
        editable=False,
        help_text="Auto-generated: VQ/YEAR/NUMBER"
    )
    quotation_date = models.DateField(auto_now_add=True)
    reference_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="Vendor's quotation reference number"
    )
    validity_date = models.DateField(
        null=True,
        blank=True,
        help_text="Quotation validity date"
    )
    payment_terms = models.CharField(max_length=200, blank=True)
    delivery_terms = models.CharField(max_length=200, blank=True)
    remarks = models.TextField(blank=True)
    # ── Currency ──────────────────────────────────────────────────────────
    currency = models.CharField(
        max_length=3, choices=CURRENCY_CHOICES, default='INR',
        help_text="Currency in which vendor quoted"
    )

    # ── Amounts (in the quotation's stated currency) ─────────────────────
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Total quotation amount (without tax)"
    )

    is_selected = models.BooleanField(
        default=False,
        help_text="Whether this quotation is selected for PO"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        help_text="User who created the quotation"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vendor_quotations'
        ordering = ['-quotation_number']
        constraints = [
            models.UniqueConstraint(
                fields=['assignment'],
                name='unique_quotation_per_assignment'
            )
        ]

    def save(self, *args, **kwargs):
        if not self.quotation_number:
            year = datetime.now().year
            last_q = VendorQuotation.objects.filter(
                quotation_number__startswith=f'VQ/{year}/'
            ).order_by('-quotation_number').first()

            if last_q:
                last_num = int(last_q.quotation_number.split('/')[-1])
                new_num = last_num + 1
            else:
                new_num = 1

            self.quotation_number = f'VQ/{year}/{new_num:04d}'

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.quotation_number} - {self.assignment.vendor.vendor_name}"



class VendorQuotationItem(models.Model):
    """Items in vendor quotation with rates (NO TAX - tax added in PO/billing)"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quotation = models.ForeignKey(
        VendorQuotation,
        on_delete=models.CASCADE,
        related_name='items'
    )
    vendor_item = models.ForeignKey(
        VendorRequisitionItem,
        on_delete=models.PROTECT,
        help_text="Reference to assigned item"
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=10, decimal_places=4)
    quoted_rate = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        help_text="Rate quoted by vendor per unit (without tax)"
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="quantity × quoted_rate (without tax)"
    )

    remarks = models.TextField(blank=True)

    class Meta:
        db_table = 'vendor_quotation_items'
        verbose_name = 'Quotation Item'
        verbose_name_plural = 'Quotation Items'

    def save(self, *args, **kwargs):
        from decimal import Decimal
        self.amount = Decimal(str(self.quantity)) * Decimal(str(self.quoted_rate))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.quotation.quotation_number} - {self.product.item_name}"
