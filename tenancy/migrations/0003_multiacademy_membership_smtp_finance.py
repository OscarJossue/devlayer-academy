from django.db import migrations, models
import core.fields


def ensure_database_shape(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        raise RuntimeError('Esta migración está preparada para PostgreSQL, que es la base oficial de Devlayer Academy.')

    with schema_editor.connection.cursor() as cursor:
        # Campos financieros que versiones anteriores podían haber creado mediante makemigrations en runtime.
        cursor.execute('ALTER TABLE tenancy_academylicense ADD COLUMN IF NOT EXISTS price numeric(12,2) DEFAULT 0 NOT NULL')
        cursor.execute('ALTER TABLE tenancy_academylicense ADD COLUMN IF NOT EXISTS amount_paid numeric(12,2) DEFAULT 0 NOT NULL')
        cursor.execute("ALTER TABLE tenancy_academylicense ADD COLUMN IF NOT EXISTS currency varchar(8) DEFAULT 'USD' NOT NULL")
        cursor.execute("ALTER TABLE tenancy_academylicense ADD COLUMN IF NOT EXISTS financial_status varchar(20) DEFAULT 'PENDING' NOT NULL")

        # SMTP aislado por academia.
        cursor.execute('ALTER TABLE tenancy_academy ADD COLUMN IF NOT EXISTS smtp_enabled boolean DEFAULT false NOT NULL')
        cursor.execute("ALTER TABLE tenancy_academy ADD COLUMN IF NOT EXISTS smtp_host varchar(255) DEFAULT '' NOT NULL")
        cursor.execute('ALTER TABLE tenancy_academy ADD COLUMN IF NOT EXISTS smtp_port integer DEFAULT 587 NOT NULL')
        cursor.execute("ALTER TABLE tenancy_academy ADD COLUMN IF NOT EXISTS smtp_username varchar(255) DEFAULT '' NOT NULL")
        cursor.execute("ALTER TABLE tenancy_academy ADD COLUMN IF NOT EXISTS smtp_password text DEFAULT '' NOT NULL")
        cursor.execute('ALTER TABLE tenancy_academy ADD COLUMN IF NOT EXISTS smtp_use_tls boolean DEFAULT true NOT NULL')
        cursor.execute('ALTER TABLE tenancy_academy ADD COLUMN IF NOT EXISTS smtp_use_ssl boolean DEFAULT false NOT NULL')
        cursor.execute("ALTER TABLE tenancy_academy ADD COLUMN IF NOT EXISTS smtp_from_email varchar(254) DEFAULT '' NOT NULL")
        cursor.execute("ALTER TABLE tenancy_academy ADD COLUMN IF NOT EXISTS smtp_from_name varchar(160) DEFAULT '' NOT NULL")

        # Membresía multiacademia: el mismo user_id puede aparecer en academias diferentes.
        cursor.execute("ALTER TABLE tenancy_academymembership ADD COLUMN IF NOT EXISTS role varchar(20) DEFAULT 'STUDENT' NOT NULL")
        cursor.execute("ALTER TABLE tenancy_academymembership ADD COLUMN IF NOT EXISTS status varchar(20) DEFAULT 'ACTIVE' NOT NULL")
        cursor.execute('ALTER TABLE tenancy_academymembership ADD COLUMN IF NOT EXISTS approved_at timestamp with time zone NULL')
        cursor.execute('ALTER TABLE tenancy_academymembership ADD COLUMN IF NOT EXISTS approved_by_id uuid NULL')

        # Elimina cualquier UNIQUE heredado que bloquee al mismo usuario en dos academias.
        cursor.execute("""
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE t.relname = 'tenancy_academymembership'
              AND c.contype = 'u'
              AND pg_get_constraintdef(c.oid) = 'UNIQUE (user_id)'
        """)
        for (constraint_name,) in cursor.fetchall():
            cursor.execute(f'ALTER TABLE tenancy_academymembership DROP CONSTRAINT IF EXISTS "{constraint_name}"')

        cursor.execute('CREATE INDEX IF NOT EXISTS tenancy_membership_user_idx ON tenancy_academymembership (user_id)')
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'unique_academy_user_membership'
                ) THEN
                    ALTER TABLE tenancy_academymembership
                    ADD CONSTRAINT unique_academy_user_membership UNIQUE (academy_id, user_id);
                END IF;
            END $$;
        """)

        # Convierte roles legados al nuevo rol por membresía sin cruzar academias.
        cursor.execute("""
            UPDATE tenancy_academymembership m
            SET role = CASE
                WHEN u.role = 'OWNER' THEN 'OWNER'
                WHEN u.role = 'PROFESSOR' THEN 'PROFESSOR'
                WHEN u.role = 'ADMIN' THEN 'ADMIN'
                ELSE 'STUDENT'
            END,
            status = COALESCE(NULLIF(m.status, ''), 'ACTIVE'),
            approved_at = COALESCE(m.approved_at, m.created_at)
            FROM accounts_user u
            WHERE u.id = m.user_id
        """)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('tenancy', '0002_academy_branding'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(ensure_database_shape, noop)],
            state_operations=[
                migrations.AlterField(
                    model_name='academylicense',
                    name='max_users',
                    field=models.PositiveIntegerField(default=0, help_text='0 = estudiantes ilimitados'),
                ),
                migrations.AddField(
                    model_name='academylicense',
                    name='price',
                    field=models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='Valor de la licencia'),
                ),
                migrations.AddField(
                    model_name='academylicense',
                    name='amount_paid',
                    field=models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='Valor cobrado'),
                ),
                migrations.AddField(
                    model_name='academylicense',
                    name='currency',
                    field=models.CharField(default='USD', max_length=8, verbose_name='Moneda'),
                ),
                migrations.AddField(
                    model_name='academylicense',
                    name='financial_status',
                    field=models.CharField(choices=[('PENDING', 'Pendiente de cobro'), ('PARTIAL', 'Pago parcial'), ('PAID', 'Pagada'), ('COURTESY', 'Cortesía')], default='PENDING', max_length=20, verbose_name='Estado financiero'),
                ),
                migrations.AddField(model_name='academy', name='smtp_enabled', field=models.BooleanField(default=False, verbose_name='SMTP habilitado')),
                migrations.AddField(model_name='academy', name='smtp_host', field=models.CharField(blank=True, max_length=255, verbose_name='Servidor SMTP')),
                migrations.AddField(model_name='academy', name='smtp_port', field=models.PositiveIntegerField(default=587, verbose_name='Puerto SMTP')),
                migrations.AddField(model_name='academy', name='smtp_username', field=models.CharField(blank=True, max_length=255, verbose_name='Usuario SMTP')),
                migrations.AddField(model_name='academy', name='smtp_password', field=core.fields.EncryptedTextField(blank=True, verbose_name='Contraseña SMTP')),
                migrations.AddField(model_name='academy', name='smtp_use_tls', field=models.BooleanField(default=True, verbose_name='Usar STARTTLS')),
                migrations.AddField(model_name='academy', name='smtp_use_ssl', field=models.BooleanField(default=False, verbose_name='Usar SSL')),
                migrations.AddField(model_name='academy', name='smtp_from_email', field=models.EmailField(blank=True, max_length=254, verbose_name='Correo remitente')),
                migrations.AddField(model_name='academy', name='smtp_from_name', field=models.CharField(blank=True, max_length=160, verbose_name='Nombre remitente')),
                migrations.AlterField(model_name='academymembership', name='user_id', field=models.UUIDField(db_index=True)),
                migrations.AddField(model_name='academymembership', name='role', field=models.CharField(choices=[('STUDENT', 'Estudiante'), ('PROFESSOR', 'Profesor'), ('ADMIN', 'Administrador'), ('OWNER', 'Dueño de academia')], default='STUDENT', max_length=20)),
                migrations.AddField(model_name='academymembership', name='status', field=models.CharField(choices=[('PENDING', 'Pendiente de aprobación'), ('ACTIVE', 'Activo'), ('BLOCKED', 'Bloqueado'), ('REJECTED', 'Rechazado')], default='ACTIVE', max_length=20)),
                migrations.AddField(model_name='academymembership', name='approved_at', field=models.DateTimeField(blank=True, null=True)),
                migrations.AddField(model_name='academymembership', name='approved_by_id', field=models.UUIDField(blank=True, null=True)),
                migrations.AddConstraint(model_name='academymembership', constraint=models.UniqueConstraint(fields=('academy', 'user_id'), name='unique_academy_user_membership')),
            ],
        ),
    ]
