# inventory/models.py

from django.db import models
import uuid


class Product(models.Model):
    """Product Master - Items/Products in inventory"""

    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item_code     = models.CharField(
                        max_length=50, unique=True, editable=False,
                        help_text="Auto-generated: ITEM/YEAR/NUMBER"
                    )
    item_name     = models.CharField(max_length=200, help_text="Product/Item name")
    description   = models.TextField(blank=True, help_text="Detailed description")
    hsn_code      = models.CharField(max_length=20, blank=True, help_text="HSN/SAC code for GST")
    unit          = models.CharField(max_length=20, default='PCS',
                                     help_text="Unit of measurement (PCS, KG, LTR, MTR, etc.)")
    current_stock = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                        help_text="Current stock quantity")
    reorder_level = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                        help_text="Minimum stock level")
    rate          = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                        help_text="Price per unit")
    is_active     = models.BooleanField(default=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'products'
        ordering = ['-created_at']
        verbose_name = 'Product'
        verbose_name_plural = 'Products'

    def save(self, *args, **kwargs):
        if not self.item_code:
            last    = Product.objects.filter(
                          item_code__startswith='ITEM/'
                      ).order_by('-item_code').first()
            new_num = int(last.item_code.split('/')[-1]) + 1 if last else 1
            self.item_code = f'ITEM/{new_num:04d}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.item_code} - {self.item_name}"
