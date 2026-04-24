import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[('ADMIN', 'Admin'), ('EMPLOYEE', 'Employee')],
                default='EMPLOYEE',
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name='UserModulePermission',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('module', models.CharField(
                    choices=[
                        ('MASTER', 'Master'),
                        ('PURCHASE', 'Purchase'),
                        ('SALES', 'Sales'),
                        ('FINANCE', 'Finance'),
                    ],
                    max_length=20,
                )),
                ('can_read', models.BooleanField(default=False)),
                ('can_write', models.BooleanField(default=False)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='module_permissions',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'User Module Permission',
                'verbose_name_plural': 'User Module Permissions',
                'db_table': 'user_module_permissions',
                'unique_together': {('user', 'module')},
            },
        ),
    ]
