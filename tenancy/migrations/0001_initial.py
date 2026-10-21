import uuid
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name='Academy',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=180)),
                ('slug', models.SlugField(max_length=190, unique=True)),
                ('legal_name', models.CharField(blank=True, max_length=220)),
                ('tax_id', models.CharField(blank=True, max_length=60)),
                ('contact_email', models.EmailField(blank=True, max_length=254)),
                ('phone', models.CharField(blank=True, max_length=40)),
                ('custom_domain', models.CharField(blank=True, max_length=255, null=True, unique=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'verbose_name': 'Academia', 'verbose_name_plural': 'Academias', 'ordering': ['name']},
        ),
        migrations.CreateModel(
            name='AcademyLicense',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('plan_name', models.CharField(default='Academy', max_length=120)),
                ('status', models.CharField(choices=[('ACTIVE', 'Activa'), ('SUSPENDED', 'Suspendida'), ('CANCELLED', 'Cancelada')], default='ACTIVE', max_length=20)),
                ('starts_at', models.DateField(default=django.utils.timezone.localdate)),
                ('ends_at', models.DateField(blank=True, null=True)),
                ('max_users', models.PositiveIntegerField(default=0, help_text='0 = usuarios ilimitados')),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('academy', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='license', to='tenancy.academy')),
            ],
            options={'verbose_name': 'Licencia de academia', 'verbose_name_plural': 'Licencias de academias'},
        ),
        migrations.CreateModel(
            name='AcademyMembership',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('user_id', models.UUIDField(db_index=True, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('academy', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='memberships', to='tenancy.academy')),
            ],
            options={'ordering': ['created_at']},
        ),
        migrations.CreateModel(
            name='AcademyCourse',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('course_id', models.UUIDField(db_index=True, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('academy', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='course_bindings', to='tenancy.academy')),
            ],
        ),
        migrations.CreateModel(
            name='AcademyCategory',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('category_id', models.UUIDField(db_index=True, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('academy', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='category_bindings', to='tenancy.academy')),
            ],
        ),
        migrations.CreateModel(
            name='AcademyBankAccount',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('bank_account_id', models.BigIntegerField(db_index=True, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('academy', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bank_bindings', to='tenancy.academy')),
            ],
        ),
        migrations.CreateModel(
            name='PlatformAuditLog',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('actor_email', models.EmailField(blank=True, max_length=254)),
                ('action', models.CharField(max_length=120)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('academy', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='platform_events', to='tenancy.academy')),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]
