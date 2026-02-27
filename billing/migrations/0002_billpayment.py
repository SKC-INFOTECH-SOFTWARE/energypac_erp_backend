# billing/migrations/0002_billpayment.py

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='BillPayment',
            fields=[
                ('id', models.UUIDField(
                    default=uuid.uuid4,
                    editable=False,
                    primary_key=True,
                    serialize=False
                )),
                ('payment_number', models.PositiveIntegerField(
                    help_text='Sequential payment number for this bill (1 = first, 2 = second, ...)'
                )),
                ('amount', models.DecimalField(
                    decimal_places=2,
                    max_digits=12,
                    help_text='Amount paid in this transaction'
                )),
                ('payment_date', models.DateField(
                    help_text='Date on which payment was received'
                )),
                ('payment_mode', models.CharField(
                    choices=[
                        ('CASH',   'Cash'),
                        ('CHEQUE', 'Cheque'),
                        ('NEFT',   'NEFT'),
                        ('RTGS',   'RTGS'),
                        ('IMPS',   'IMPS'),
                        ('UPI',    'UPI'),
                        ('OTHER',  'Other'),
                    ],
                    default='CASH',
                    max_length=20,
                    help_text='Mode of payment'
                )),
                ('reference_number', models.CharField(
                    blank=True,
                    max_length=100,
                    help_text='Cheque number / UTR / transaction reference'
                )),
                ('remarks', models.TextField(blank=True)),
                ('total_paid_after', models.DecimalField(
                    decimal_places=2,
                    max_digits=12,
                    help_text='Cumulative amount_paid on the bill AFTER this transaction'
                )),
                ('balance_after', models.DecimalField(
                    decimal_places=2,
                    max_digits=12,
                    help_text='Remaining balance on the bill AFTER this transaction'
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('bill', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='payments',
                    to='billing.bill',
                    help_text='Bill this payment belongs to'
                )),
                ('recorded_by', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    to=settings.AUTH_USER_MODEL,
                    help_text='User who recorded this payment'
                )),
            ],
            options={
                'verbose_name': 'Bill Payment',
                'verbose_name_plural': 'Bill Payments',
                'db_table': 'bill_payments',
                'ordering': ['bill', 'payment_number'],
            },
        ),
    ]
