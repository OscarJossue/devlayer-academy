import uuid

from django.db import migrations, models
import django.db.models.deletion


def ensure_plan_schema(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        raise RuntimeError('Esta migración está preparada para PostgreSQL, base oficial de Devlayer Academy.')

    with schema_editor.connection.cursor() as cursor:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tenancy_academyplan (
                id uuid PRIMARY KEY,
                name varchar(120) NOT NULL,
                code varchar(140) NOT NULL,
                description text NOT NULL DEFAULT '',
                max_students integer NOT NULL DEFAULT 100 CHECK (max_students >= 0),
                max_professors integer NOT NULL DEFAULT 5 CHECK (max_professors >= 0),
                max_admins integer NOT NULL DEFAULT 2 CHECK (max_admins >= 0),
                price numeric(12,2) NOT NULL DEFAULT 0,
                currency varchar(8) NOT NULL DEFAULT 'USD',
                duration_days integer NOT NULL DEFAULT 365 CHECK (duration_days >= 0),
                is_active boolean NOT NULL DEFAULT true,
                created_at timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS tenancy_academyplan_name_uniq ON tenancy_academyplan (name)')
        cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS tenancy_academyplan_code_uniq ON tenancy_academyplan (code)')

        cursor.execute('ALTER TABLE tenancy_academylicense ADD COLUMN IF NOT EXISTS max_professors integer DEFAULT 0 NOT NULL')
        cursor.execute('ALTER TABLE tenancy_academylicense ADD COLUMN IF NOT EXISTS max_admins integer DEFAULT 0 NOT NULL')
        cursor.execute('ALTER TABLE tenancy_academylicense ADD COLUMN IF NOT EXISTS plan_id uuid NULL')
        cursor.execute('CREATE INDEX IF NOT EXISTS tenancy_academylicense_plan_idx ON tenancy_academylicense (plan_id)')
        cursor.execute('''
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'tenancy_academylicense_plan_fk'
                ) THEN
                    ALTER TABLE tenancy_academylicense
                    ADD CONSTRAINT tenancy_academylicense_plan_fk
                    FOREIGN KEY (plan_id) REFERENCES tenancy_academyplan(id)
                    ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;
                END IF;
            END $$;
        ''')


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('tenancy', '0003_multiacademy_membership_smtp_finance')]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(ensure_plan_schema, noop)],
            state_operations=[
                migrations.CreateModel(
                    name='AcademyPlan',
                    fields=[
                        ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                        ('name', models.CharField(max_length=120, unique=True, verbose_name='Nombre del plan')),
                        ('code', models.SlugField(blank=True, max_length=140, unique=True, verbose_name='Código')),
                        ('description', models.TextField(blank=True, verbose_name='Descripción')),
                        ('max_students', models.PositiveIntegerField(default=100, help_text='0 = ilimitados', verbose_name='Máximo de estudiantes activos')),
                        ('max_professors', models.PositiveIntegerField(default=5, help_text='0 = ilimitados', verbose_name='Máximo de profesores')),
                        ('max_admins', models.PositiveIntegerField(default=2, help_text='0 = ilimitados', verbose_name='Máximo de administradores')),
                        ('price', models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='Precio')),
                        ('currency', models.CharField(default='USD', max_length=8, verbose_name='Moneda')),
                        ('duration_days', models.PositiveIntegerField(default=365, help_text='0 = sin vencimiento automático', verbose_name='Duración en días')),
                        ('is_active', models.BooleanField(default=True, verbose_name='Disponible para nuevas licencias')),
                        ('created_at', models.DateTimeField(auto_now_add=True)),
                        ('updated_at', models.DateTimeField(auto_now=True)),
                    ],
                    options={'verbose_name': 'Plan de academia', 'verbose_name_plural': 'Planes de academias', 'ordering': ['price', 'name']},
                ),
                migrations.AddField(
                    model_name='academylicense',
                    name='plan',
                    field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='licenses', to='tenancy.academyplan', verbose_name='Plan comercial'),
                ),
                migrations.AddField(
                    model_name='academylicense',
                    name='max_professors',
                    field=models.PositiveIntegerField(default=0, help_text='0 = profesores ilimitados'),
                ),
                migrations.AddField(
                    model_name='academylicense',
                    name='max_admins',
                    field=models.PositiveIntegerField(default=0, help_text='0 = administradores ilimitados'),
                ),
            ],
        ),
    ]
