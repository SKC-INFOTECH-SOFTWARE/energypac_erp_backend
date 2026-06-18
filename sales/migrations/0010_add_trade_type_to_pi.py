# Adds trade_type (Domestic/International) to Proforma Invoice

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0009_add_source_to_pi'),
    ]

    operations = [
        migrations.AddField(
            model_name='proformainvoice',
            name='trade_type',
            field=models.CharField(
                choices=[('DOMESTIC', 'Domestic'), ('INTERNATIONAL', 'International')],
                default='DOMESTIC',
                help_text='Domestic (PI Bill + GST) or International (Commercial Invoice, no GST)',
                max_length=15,
            ),
        ),
    ]
