from django.core.management.base import BaseCommand
from accounts.models import User, UserModulePermission, MODULE_CHOICES


class Command(BaseCommand):
    help = 'Create the initial admin user with full module permissions'

    def add_arguments(self, parser):
        parser.add_argument('--employee-code', type=str, default='ADMIN001')
        parser.add_argument('--password', type=str, default='admin@123')
        parser.add_argument('--first-name', type=str, default='System')
        parser.add_argument('--last-name', type=str, default='Admin')
        parser.add_argument('--email', type=str, default='admin@energypac.com')

    def handle(self, *args, **options):
        employee_code = options['employee_code']

        if User.objects.filter(employee_code=employee_code).exists():
            self.stdout.write(self.style.WARNING(
                f'Admin user with employee_code "{employee_code}" already exists.'
            ))
            return

        user = User(
            employee_code=employee_code,
            username=employee_code,
            first_name=options['first_name'],
            last_name=options['last_name'],
            email=options['email'],
            role='ADMIN',
            is_staff=True,
        )
        user.set_password(options['password'])
        user.save()

        for module_key, _ in MODULE_CHOICES:
            UserModulePermission.objects.create(
                user=user, module=module_key, can_read=True, can_write=True
            )

        self.stdout.write(self.style.SUCCESS(
            f'Admin user created: {employee_code} / {options["password"]}'
        ))
