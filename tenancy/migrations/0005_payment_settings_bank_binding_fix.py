from django.db import migrations, models


def _drop_bank_account_indexes(cursor):
    """Elimina constraints/índices creados cuando bank_account_id era varchar.

    PostgreSQL crea un índice *_like con varchar_pattern_ops para CharField(unique=True).
    Ese índice impide convertir la columna a bigint, por eso debe retirarse antes del ALTER TYPE.
    """
    # Primero quitamos constraints UNIQUE asociadas a la columna.
    cursor.execute(
        """
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_class tbl ON tbl.oid = con.conrelid
        JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
        JOIN pg_attribute att ON att.attrelid = tbl.oid
        WHERE ns.nspname = current_schema()
          AND tbl.relname = 'tenancy_academybankaccount'
          AND att.attname = 'bank_account_id'
          AND att.attnum = ANY(con.conkey)
          AND con.contype IN ('u')
        """
    )
    for (constraint_name,) in cursor.fetchall():
        cursor.execute(
            f'ALTER TABLE tenancy_academybankaccount DROP CONSTRAINT IF EXISTS "{constraint_name}"'
        )

    # Luego quitamos índices no respaldados por constraints, incluido *_like/varchar_pattern_ops.
    cursor.execute(
        """
        SELECT DISTINCT idx.relname
        FROM pg_class tbl
        JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
        JOIN pg_index i ON i.indrelid = tbl.oid
        JOIN pg_class idx ON idx.oid = i.indexrelid
        JOIN pg_attribute att
          ON att.attrelid = tbl.oid
         AND att.attnum = ANY(i.indkey)
        LEFT JOIN pg_constraint con ON con.conindid = idx.oid
        WHERE ns.nspname = current_schema()
          AND tbl.relname = 'tenancy_academybankaccount'
          AND att.attname = 'bank_account_id'
          AND con.oid IS NULL
        """
    )
    for (index_name,) in cursor.fetchall():
        cursor.execute(f'DROP INDEX IF EXISTS "{index_name}"')


def _ensure_bigint_unique(cursor):
    cursor.execute(
        """
        SELECT data_type
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'tenancy_academybankaccount'
          AND column_name = 'bank_account_id'
        """
    )
    row = cursor.fetchone()
    if not row:
        return

    current_type = row[0]
    if current_type in ('character varying', 'text'):
        # Conservamos únicamente IDs válidos. Las filas inválidas no pueden apuntar a billing_bankaccount.
        cursor.execute(
            """
            DELETE FROM tenancy_academybankaccount
            WHERE btrim(bank_account_id::text) = ''
               OR btrim(bank_account_id::text) !~ '^[0-9]+$'
            """
        )
        _drop_bank_account_indexes(cursor)
        cursor.execute(
            """
            ALTER TABLE tenancy_academybankaccount
            ALTER COLUMN bank_account_id TYPE bigint
            USING btrim(bank_account_id::text)::bigint
            """
        )

    # Garantiza la unicidad que declara el modelo BigIntegerField(unique=True).
    cursor.execute(
        """
        SELECT 1
        FROM pg_constraint con
        JOIN pg_class tbl ON tbl.oid = con.conrelid
        JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
        JOIN pg_attribute att ON att.attrelid = tbl.oid
        WHERE ns.nspname = current_schema()
          AND tbl.relname = 'tenancy_academybankaccount'
          AND att.attname = 'bank_account_id'
          AND att.attnum = ANY(con.conkey)
          AND con.contype = 'u'
        LIMIT 1
        """
    )
    if cursor.fetchone() is None:
        cursor.execute(
            """
            ALTER TABLE tenancy_academybankaccount
            ADD CONSTRAINT tenancy_academybankaccount_bank_account_id_key
            UNIQUE (bank_account_id)
            """
        )


def ensure_schema(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        raise RuntimeError('Esta migración está preparada para PostgreSQL.')

    with schema_editor.connection.cursor() as cursor:
        # Métodos de pago independientes por academia.
        cursor.execute(
            'ALTER TABLE tenancy_academy ADD COLUMN IF NOT EXISTS '
            'payment_transfer_enabled boolean DEFAULT true NOT NULL'
        )
        cursor.execute(
            'ALTER TABLE tenancy_academy ADD COLUMN IF NOT EXISTS '
            'payment_whatsapp_enabled boolean DEFAULT false NOT NULL'
        )
        cursor.execute(
            "ALTER TABLE tenancy_academy ADD COLUMN IF NOT EXISTS "
            "payment_whatsapp_number varchar(30) DEFAULT '' NOT NULL"
        )
        cursor.execute(
            "ALTER TABLE tenancy_academy ADD COLUMN IF NOT EXISTS "
            "payment_instructions text DEFAULT '' NOT NULL"
        )

        _ensure_bigint_unique(cursor)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('tenancy', '0004_academy_plans_limits')]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(ensure_schema, noop)],
            state_operations=[
                migrations.AddField(
                    model_name='academy',
                    name='payment_transfer_enabled',
                    field=models.BooleanField(
                        default=True,
                        verbose_name='Aceptar transferencia bancaria',
                    ),
                ),
                migrations.AddField(
                    model_name='academy',
                    name='payment_whatsapp_enabled',
                    field=models.BooleanField(
                        default=False,
                        verbose_name='Aceptar reporte por WhatsApp',
                    ),
                ),
                migrations.AddField(
                    model_name='academy',
                    name='payment_whatsapp_number',
                    field=models.CharField(
                        blank=True,
                        max_length=30,
                        verbose_name='WhatsApp para pagos',
                    ),
                ),
                migrations.AddField(
                    model_name='academy',
                    name='payment_instructions',
                    field=models.TextField(
                        blank=True,
                        verbose_name='Indicaciones generales de pago',
                    ),
                ),
                migrations.AlterField(
                    model_name='academybankaccount',
                    name='bank_account_id',
                    field=models.BigIntegerField(db_index=True, unique=True),
                ),
            ],
        ),
    ]
