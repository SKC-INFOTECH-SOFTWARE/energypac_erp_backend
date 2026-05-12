
from django.conf import settings
from django.db import migrations, models


def remove_duplicate_assignments(apps, schema_editor):
    """Keep one assignment per (requisition, vendor) pair, migrate children, delete the rest."""
    VendorRequisitionAssignment = apps.get_model('requisitions', 'VendorRequisitionAssignment')
    VendorRequisitionItem = apps.get_model('requisitions', 'VendorRequisitionItem')
    VendorQuotation = apps.get_model('requisitions', 'VendorQuotation')
    VendorQuotationItem = apps.get_model('requisitions', 'VendorQuotationItem')

    from collections import defaultdict
    groups = defaultdict(list)

    for a in VendorRequisitionAssignment.objects.order_by('created_at'):
        key = (str(a.requisition_id), str(a.vendor_id))
        groups[key].append(a)

    for key, assignments in groups.items():
        if len(assignments) <= 1:
            continue

        keep = assignments[0]
        duplicates = assignments[1:]

        for dup in duplicates:
            VendorQuotationItem.objects.filter(quotation__assignment_id=dup.id).delete()
            VendorQuotation.objects.filter(assignment_id=dup.id).delete()
            VendorRequisitionItem.objects.filter(assignment_id=dup.id).delete()
            VendorRequisitionAssignment.objects.filter(id=dup.id).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('requisitions', '0006_allow_decimal_places_in_quotation_items'),
        ('vendors', '0002_vendor_account_name_vendor_swift_code_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(remove_duplicate_assignments, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='vendorrequisitionassignment',
            constraint=models.UniqueConstraint(fields=('requisition', 'vendor'), name='unique_vendor_per_requisition'),
        ),
    ]
