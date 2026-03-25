"""
One-time management command to backfill IncomingPayment records
from existing BillPayment records.

Run:  python manage.py sync_bill_payments
"""
from django.core.management.base import BaseCommand
from billing.models import BillPayment
from finance.models import IncomingPayment


class Command(BaseCommand):
    help = 'Sync existing BillPayment records into IncomingPayment (one-time backfill)'

    def handle(self, *args, **options):
        created = 0
        skipped = 0

        for bp in BillPayment.objects.select_related('bill', 'recorded_by').order_by('bill', 'payment_number'):
            # Skip if an IncomingPayment already exists for this exact bill + payment_number
            exists = IncomingPayment.objects.filter(
                bill=bp.bill,
                payment_number=bp.payment_number,
            ).exists()

            if exists:
                skipped += 1
                continue

            IncomingPayment.objects.create(
                bill             = bp.bill,
                payment_number   = bp.payment_number,
                amount           = bp.amount,
                payment_date     = bp.payment_date,
                payment_mode     = bp.payment_mode,
                reference_number = bp.reference_number,
                remarks          = bp.remarks,
                total_paid_after = bp.total_paid_after,
                balance_after    = bp.balance_after,
                recorded_by      = bp.recorded_by,
            )
            created += 1

        self.stdout.write(self.style.SUCCESS(
            f'Done — {created} IncomingPayment(s) created, {skipped} already existed.'
        ))
