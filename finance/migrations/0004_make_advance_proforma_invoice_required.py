import django.db.models.deletion
from django.db import migrations, models


def delete_orphan_advances(apps, schema_editor):
    AdvancePayment = apps.get_model('finance', 'AdvancePayment')
    AdvancePayment.objects.filter(proforma_invoice__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0003_alter_purchasepayment_options_and_more'),
        ('sales', '0005_proformainvoice_proformainvoiceitem'),
    ]

    operations = [
        migrations.RunPython(delete_orphan_advances, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='advancepayment',
            name='proforma_invoice',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='advance_payments',
                to='sales.proformainvoice',
            ),
        ),
    ]
