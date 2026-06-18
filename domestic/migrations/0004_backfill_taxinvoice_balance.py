from django.db import migrations
from decimal import Decimal


def backfill_balance(apps, schema_editor):
    TaxInvoice = apps.get_model('domestic', 'TaxInvoice')
    for ti in TaxInvoice.objects.all():
        paid = ti.amount_paid or Decimal('0')
        total = ti.total_amount_after_tax or Decimal('0')
        balance = total - paid
        if balance < 0:
            balance = Decimal('0')
        ti.balance = balance
        if ti.status not in ('CANCELLED', 'DRAFT'):
            if paid <= 0:
                ti.status = 'GENERATED'
            elif balance <= 0:
                ti.status = 'PAID'
            else:
                ti.status = 'PARTIALLY_PAID'
        ti.save(update_fields=['balance', 'status'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('domestic', '0003_taxinvoice_amount_paid_taxinvoice_balance_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_balance, noop),
    ]
