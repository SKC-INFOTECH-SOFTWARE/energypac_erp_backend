# Generated for source-type tracking on Proforma Invoice

from django.db import migrations, models


def backfill_source(apps, schema_editor):
    """
    Before this field existed, a PI with no requisition meant a stock sale.
    Preserve that meaning: requisition-linked -> REQUISITION, else -> STOCK_SALE.
    Brand-new DIRECT PIs only appear after this migration.
    """
    ProformaInvoice = apps.get_model('sales', 'ProformaInvoice')
    ProformaInvoice.objects.filter(requisition__isnull=False).update(source='REQUISITION')
    ProformaInvoice.objects.filter(requisition__isnull=True).update(source='STOCK_SALE')


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0008_make_requisition_nullable_on_pi'),
    ]

    operations = [
        migrations.AddField(
            model_name='proformainvoice',
            name='source',
            field=models.CharField(
                choices=[
                    ('REQUISITION', 'From Requisition'),
                    ('STOCK_SALE', 'Stock Sale'),
                    ('DIRECT', 'Direct PI'),
                ],
                default='REQUISITION',
                help_text='How this PI was created — requisition flow, stock sale, or direct',
                max_length=20,
            ),
        ),
        migrations.RunPython(backfill_source, noop_reverse),
    ]
