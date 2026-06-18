from django.db import migrations
from decimal import Decimal


def backfill_balance(apps, schema_editor):
    TransportEntry = apps.get_model('transport', 'TransportEntry')
    for e in TransportEntry.objects.all():
        paid = e.amount_paid or Decimal('0')
        total = e.total_cost or Decimal('0')
        balance = total - paid
        if balance < 0:
            balance = Decimal('0')
        e.balance = balance
        if e.status == 'CANCELLED':
            pass
        elif paid <= 0:
            e.payment_status = 'UNPAID'
        elif balance <= 0:
            e.payment_status = 'PAID'
        else:
            e.payment_status = 'PARTIALLY_PAID'
        e.save(update_fields=['balance', 'payment_status'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('transport', '0003_transportentry_amount_paid_transportentry_balance_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_balance, noop),
    ]
