from django.db import models
from django.conf import settings
from datetime import datetime
from decimal import Decimal
import uuid

from sales.models import ProformaInvoice, ProformaInvoiceItem


# ═════════════════════════════════════════════════════════════════════════════
# Commercial Invoice — export billing doc for INTERNATIONAL PIs (NO GST/tax)
# Header is prefilled from the PI and kept editable; extra export-specific data
# is captured here. The Packing List is generated from this Commercial Invoice.
# ═════════════════════════════════════════════════════════════════════════════

class CommercialInvoice(models.Model):
    STATUS_CHOICES = [
        ('DRAFT',     'Draft'),
        ('GENERATED', 'Generated'),
        ('CANCELLED', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ci_number = models.CharField(max_length=50, unique=True, editable=False)

    proforma_invoice = models.ForeignKey(
        ProformaInvoice, on_delete=models.PROTECT, related_name='commercial_invoices',
    )

    # ── Header — top-right invoice meta ──────────────────────────────────────
    invoice_no   = models.CharField(max_length=100, blank=True, default='')   # "Invoice No & Date" no part
    invoice_date = models.DateField(null=True, blank=True)
    exporters_ref = models.CharField(max_length=200, blank=True, default='')  # IEC NO. ...
    gst_no        = models.CharField(max_length=50, blank=True, default='')
    buyers_order_no   = models.CharField(max_length=100, blank=True, default='')
    buyers_order_date = models.DateField(null=True, blank=True)

    # ── Header — parties (prefilled from PI, editable) ───────────────────────
    exporter               = models.TextField(blank=True, default='')
    consigned_to_order_of  = models.TextField(blank=True, default='')   # LC bank
    importer_notify_party  = models.TextField(blank=True, default='')
    applicant              = models.TextField(blank=True, default='')

    # ── Header — terms & logistics ───────────────────────────────────────────
    terms_of_delivery             = models.TextField(blank=True, default='')
    terms_of_delivery_and_payment = models.TextField(blank=True, default='')  # D/C, IRC, insurance block
    place_of_supply   = models.CharField(max_length=200, blank=True, default='')
    vessel_flight_no  = models.CharField(max_length=200, blank=True, default='')
    port_of_loading   = models.CharField(max_length=200, blank=True, default='')
    port_of_discharge = models.CharField(max_length=200, blank=True, default='')
    place_of_delivery = models.CharField(max_length=200, blank=True, default='')
    pre_carriage_by   = models.CharField(max_length=200, blank=True, default='')
    place_of_receipt  = models.CharField(max_length=200, blank=True, default='')
    country_of_origin = models.CharField(max_length=100, blank=True, default='')
    final_destination = models.CharField(max_length=200, blank=True, default='')

    currency = models.CharField(max_length=10, default='USD')

    # ── Marks & Nos / Container No. — a single range for the whole shipment ───
    marks_from = models.CharField(max_length=200, blank=True, default='')
    marks_to   = models.CharField(max_length=200, blank=True, default='')

    # ── Totals (NO GST — export) ─────────────────────────────────────────────
    total_fca_value = models.DecimalField(max_digits=14, decimal_places=2, default=0,
                                          help_text="Sum of item totals")
    total_freight   = models.DecimalField(max_digits=14, decimal_places=2, default=0,
                                          help_text="Freight charge (user input)")
    total_cpt_value = models.DecimalField(max_digits=14, decimal_places=2, default=0,
                                          help_text="FCA + Freight")
    amount_in_words = models.CharField(max_length=400, blank=True, default='')

    # ── Footer ───────────────────────────────────────────────────────────────
    project_name = models.TextField(blank=True, default='')
    declarations = models.JSONField(default=list, blank=True)   # list of declaration lines
    lut_no       = models.CharField(max_length=200, blank=True, default='')

    status     = models.CharField(max_length=20, choices=STATUS_CHOICES, default='GENERATED')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   related_name='commercial_invoices_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'commercial_invoices'
        ordering = ['-ci_number']

    def save(self, *args, **kwargs):
        if not self.ci_number:
            year = datetime.now().year
            prefix = f'CI/{year}/'
            last = CommercialInvoice.objects.filter(
                ci_number__startswith=prefix
            ).order_by('-ci_number').first()
            new_num = int(last.ci_number.split('/')[-1]) + 1 if last else 1
            self.ci_number = f'{prefix}{new_num:04d}'
        super().save(*args, **kwargs)

    def recalc_totals(self):
        self.total_fca_value = sum((i.total_amount for i in self.items.all()), Decimal('0'))
        self.total_cpt_value = self.total_fca_value + (self.total_freight or Decimal('0'))

    def __str__(self):
        return self.ci_number


class CommercialInvoiceItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    commercial_invoice = models.ForeignKey(
        CommercialInvoice, on_delete=models.CASCADE, related_name='items',
    )
    pi_item = models.ForeignKey(ProformaInvoiceItem, on_delete=models.SET_NULL,
                                null=True, blank=True)

    marks_nos    = models.CharField(max_length=200, blank=True, default='')   # Marks & Nos / Container No
    no_kind_pkgs = models.CharField(max_length=200, blank=True, default='')   # No & Kind of Pkgs
    description  = models.TextField(blank=True, default='')                   # multi-line incl HS code
    hs_code      = models.CharField(max_length=50, blank=True, default='')
    quantity     = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit         = models.CharField(max_length=20, blank=True, default='Nos.')   # "Set." / "Nos."
    unit_price   = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    sort_order   = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'commercial_invoice_items'
        ordering = ['sort_order']

    def save(self, *args, **kwargs):
        self.total_amount = Decimal(str(self.quantity or 0)) * Decimal(str(self.unit_price or 0))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.commercial_invoice.ci_number} - item"


# ═════════════════════════════════════════════════════════════════════════════
# Packing List — generated from a Commercial Invoice. Shares the CI header;
# replaces price columns with Nett/Gross weight, captured per item from user.
# ═════════════════════════════════════════════════════════════════════════════

class PackingList(models.Model):
    STATUS_CHOICES = [
        ('DRAFT',     'Draft'),
        ('GENERATED', 'Generated'),
        ('CANCELLED', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pl_number = models.CharField(max_length=50, unique=True, editable=False)

    commercial_invoice = models.ForeignKey(
        CommercialInvoice, on_delete=models.PROTECT, related_name='packing_lists',
    )

    packing_specification = models.TextField(blank=True, default='')
    lut_no = models.CharField(max_length=200, blank=True, default='')

    total_nett_weight  = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    total_gross_weight = models.DecimalField(max_digits=14, decimal_places=3, default=0)

    status     = models.CharField(max_length=20, choices=STATUS_CHOICES, default='GENERATED')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   related_name='packing_lists_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'packing_lists'
        ordering = ['-pl_number']

    def save(self, *args, **kwargs):
        if not self.pl_number:
            year = datetime.now().year
            prefix = f'PL/{year}/'
            last = PackingList.objects.filter(
                pl_number__startswith=prefix
            ).order_by('-pl_number').first()
            new_num = int(last.pl_number.split('/')[-1]) + 1 if last else 1
            self.pl_number = f'{prefix}{new_num:04d}'
        super().save(*args, **kwargs)

    def recalc_totals(self):
        self.total_nett_weight = sum((i.nett_weight for i in self.items.all()), Decimal('0'))
        self.total_gross_weight = sum((i.gross_weight for i in self.items.all()), Decimal('0'))

    def __str__(self):
        return self.pl_number


class PackingListItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    packing_list = models.ForeignKey(
        PackingList, on_delete=models.CASCADE, related_name='items',
    )
    ci_item = models.ForeignKey(CommercialInvoiceItem, on_delete=models.SET_NULL,
                                null=True, blank=True)

    # snapshot of the descriptive columns so the PL renders standalone
    marks_nos    = models.CharField(max_length=200, blank=True, default='')
    no_kind_pkgs = models.CharField(max_length=200, blank=True, default='')
    description  = models.TextField(blank=True, default='')
    hs_code      = models.CharField(max_length=50, blank=True, default='')
    quantity     = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit         = models.CharField(max_length=20, blank=True, default='Nos.')

    nett_weight  = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    gross_weight = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    sort_order   = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'packing_list_items'
        ordering = ['sort_order']

    def __str__(self):
        return f"{self.packing_list.pl_number} - item"
