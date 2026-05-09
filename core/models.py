from django.db import models
from django.conf import settings
import uuid


CURRENCY_CHOICES = [
    ('INR', 'Indian Rupee'),
    ('USD', 'US Dollar'),
]


class ExchangeRate(models.Model):
    """
    Stores the admin-managed USD to INR exchange rate.
    The latest active rate is used for all new transactions.
    Historical rates are preserved for audit.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    rate = models.DecimalField(
        max_digits=10, decimal_places=4,
        help_text="1 USD = ? INR (e.g. 83.5000)"
    )

    effective_date = models.DateField(
        help_text="Date from which this rate is effective"
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Only the latest active rate is used for new transactions"
    )

    remarks = models.CharField(max_length=200, blank=True)

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True, blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'exchange_rates'
        ordering = ['-effective_date', '-created_at']
        verbose_name = 'Exchange Rate'
        verbose_name_plural = 'Exchange Rates'

    @classmethod
    def get_current_rate(cls):
        """Return the latest active USD→INR rate. Raises if none configured."""
        rate_obj = cls.objects.filter(is_active=True).order_by('-effective_date', '-created_at').first()
        if not rate_obj:
            raise ValueError("No active USD to INR exchange rate configured. Please set one in Admin.")
        return rate_obj.rate

    def save(self, *args, **kwargs):
        if self.is_active:
            ExchangeRate.objects.filter(is_active=True).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"1 USD = {self.rate} INR (effective {self.effective_date})"
