from django.db import models
from django.conf import settings
from inventory.models import Product
import uuid
from datetime import datetime


class ClientQuery(models.Model):
    """Client Query/Inquiry - Customer requests"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    query_number = models.CharField(
        max_length=50,
        unique=True,
        editable=False,
        help_text="Auto-generated: CQ/YEAR/NUMBER"
    )
    client_name = models.CharField(max_length=200, help_text="Client/Customer name")
    contact_person = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=15, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)

    query_date = models.DateField(help_text="Date of query received")
    pdf_file = models.CharField(
        max_length=500,
        blank=True,
        help_text="Path to uploaded PDF file in container"
    )
    remarks = models.TextField(blank=True, help_text="Query details and remarks")

    status = models.CharField(
        max_length=20,
        choices=[
            ('PENDING', 'Pending'),
            ('QUOTATION_SENT', 'Quotation Sent'),
            ('CONVERTED', 'Converted to Sale'),
            ('REJECTED', 'Rejected'),
        ],
        default='PENDING'
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='client_queries_created'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'client_queries'
        ordering = ['-query_number']
        verbose_name = 'Client Query'
        verbose_name_plural = 'Client Queries'

    def save(self, *args, **kwargs):
        if not self.query_number:
            year = datetime.now().year
            last_query = ClientQuery.objects.filter(
                query_number__startswith=f'CQ/{year}/'
            ).order_by('-query_number').first()

            new_num = int(last_query.query_number.split('/')[-1]) + 1 if last_query else 1
            self.query_number = f'CQ/{year}/{new_num:04d}'

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.query_number} - {self.client_name}"


class SalesQuotation(models.Model):
    """Sales Quotation generated from client query"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quotation_number = models.CharField(
        max_length=50,
        unique=True,
        editable=False,
        help_text="Auto-generated: SQ/YEAR/NUMBER"
    )
    client_query = models.ForeignKey(
        ClientQuery,
        on_delete=models.PROTECT,
        related_name='quotations'
    )

    quotation_date = models.DateField(help_text="Date of quotation")
    validity_date = models.DateField(
        null=True,
        blank=True,
        help_text="Valid until date"
    )

    payment_terms = models.CharField(max_length=200, blank=True)
    delivery_terms = models.CharField(max_length=200, blank=True)
    remarks = models.TextField(blank=True)

    # Tax configuration
    cgst_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="CGST percentage"
    )
    sgst_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="SGST percentage"
    )
    igst_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="IGST percentage (for interstate)"
    )

    # Amounts
    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Sum of all items before tax"
    )
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    igst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Subtotal + all taxes"
    )

    status = models.CharField(
        max_length=20,
        choices=[
            ('DRAFT', 'Draft'),
            ('SENT', 'Sent to Client'),
            ('ACCEPTED', 'Accepted'),
            ('REJECTED', 'Rejected'),
        ],
        default='DRAFT'
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sales_quotations'
        ordering = ['-quotation_number']
        verbose_name = 'Sales Quotation'
        verbose_name_plural = 'Sales Quotations'

    def save(self, *args, **kwargs):
        if not self.quotation_number:
            year = datetime.now().year
            last_quote = SalesQuotation.objects.filter(
                quotation_number__startswith=f'SQ/{year}/'
            ).order_by('-quotation_number').first()

            new_num = int(last_quote.quotation_number.split('/')[-1]) + 1 if last_quote else 1
            self.quotation_number = f'SQ/{year}/{new_num:04d}'

        super().save(*args, **kwargs)

    def calculate_totals(self):
        """Calculate all amounts based on items"""
        self.subtotal = sum(item.amount for item in self.items.all())

        # Calculate taxes
        self.cgst_amount = (self.subtotal * self.cgst_percentage) / 100
        self.sgst_amount = (self.subtotal * self.sgst_percentage) / 100
        self.igst_amount = (self.subtotal * self.igst_percentage) / 100

        self.total_amount = (
            self.subtotal +
            self.cgst_amount +
            self.sgst_amount +
            self.igst_amount
        )

        self.save()

    def __str__(self):
        return f"{self.quotation_number} - {self.client_query.client_name}"


class SalesQuotationItem(models.Model):
    """Items in sales quotation - can be from stock or manual entry"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quotation = models.ForeignKey(
        SalesQuotation,
        on_delete=models.CASCADE,
        related_name='items'
    )

    # Link to product (if from stock)
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Product from inventory (optional)"
    )

    # Manual entry fields (used when product is not from stock)
    item_code = models.CharField(
        max_length=50,
        blank=True,
        help_text="Item code (auto-filled from product or manual)"
    )
    item_name = models.CharField(
        max_length=200,
        help_text="Item name (auto-filled from product or manual)"
    )
    description = models.TextField(blank=True)
    hsn_code = models.CharField(max_length=20, blank=True)
    unit = models.CharField(max_length=20, default='PCS')

    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Rate per unit"
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="quantity × rate"
    )

    remarks = models.TextField(blank=True)

    class Meta:
        db_table = 'sales_quotation_items'
        verbose_name = 'Quotation Item'
        verbose_name_plural = 'Quotation Items'

    def save(self, *args, **kwargs):
        # Auto-fill from product if linked
        if self.product:
            self.item_code = self.product.item_code
            self.item_name = self.product.item_name
            self.hsn_code = self.product.hsn_code
            self.unit = self.product.unit
            if not self.description:
                self.description = self.product.description

            # If manual entry with product link, add to product master
            # (This happens when user selects manual but wants to save to inventory)

        # Calculate amount
        self.amount = self.quantity * self.rate

        super().save(*args, **kwargs)

        # Auto-add to product table if manual entry with all details
        if not self.product and self.item_code and self.item_name:
            # Check if product exists
            existing_product = Product.objects.filter(item_code=self.item_code).first()
            if not existing_product:
                # Create new product
                Product.objects.create(
                    item_code=self.item_code,
                    item_name=self.item_name,
                    description=self.description,
                    hsn_code=self.hsn_code,
                    unit=self.unit,
                    rate=self.rate,
                    current_stock=0,  # Manual entries start with 0 stock
                    reorder_level=0,
                    is_active=True
                )

    def __str__(self):
        return f"{self.quotation.quotation_number} - {self.item_name}"
