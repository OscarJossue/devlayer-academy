from django.db import migrations


def _columns(connection, table):
    with connection.cursor() as cursor:
        return {item.name for item in connection.introspection.get_table_description(cursor, table)}


def ensure_course_discount_columns(apps, schema_editor):
    connection = schema_editor.connection
    if 'catalog_course' not in set(connection.introspection.table_names()):
        return
    columns = _columns(connection, 'catalog_course')
    dt_type = 'timestamp with time zone' if connection.vendor == 'postgresql' else 'datetime'
    additions = [
        ('discount_enabled', 'boolean NOT NULL DEFAULT FALSE'),
        ('discount_type', "varchar(20) NOT NULL DEFAULT 'PERCENTAGE'"),
        ('discount_value', 'numeric(10,2) NOT NULL DEFAULT 0'),
        ('discount_starts_at', f'{dt_type} NULL'),
        ('discount_ends_at', f'{dt_type} NULL'),
    ]
    with connection.cursor() as cursor:
        for name, sql_type in additions:
            if name not in columns:
                cursor.execute(f'ALTER TABLE catalog_course ADD COLUMN {name} {sql_type}')


def noop_reverse(apps, schema_editor):
    # No eliminamos columnas al revertir para no perder promociones configuradas.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('tenancy', '0012_platform_email_settings'),
    ]

    operations = [
        migrations.RunPython(ensure_course_discount_columns, noop_reverse),
    ]
