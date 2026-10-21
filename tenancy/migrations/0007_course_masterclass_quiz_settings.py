from django.db import migrations


def _columns(connection, table):
    with connection.cursor() as cursor:
        return {item.name for item in connection.introspection.get_table_description(cursor, table)}


def ensure_course_and_quiz_columns(apps, schema_editor):
    connection = schema_editor.connection
    tables = set(connection.introspection.table_names())
    vendor = connection.vendor

    if 'catalog_course' in tables:
        columns = _columns(connection, 'catalog_course')
        scheduled_type = 'timestamp with time zone' if vendor == 'postgresql' else 'datetime'
        additions = [
            ('masterclass_enabled', 'boolean NOT NULL DEFAULT FALSE'),
            ('masterclass_title', "varchar(180) NOT NULL DEFAULT 'Clase magistral y resolución de dudas'"),
            ('masterclass_description', "text NOT NULL DEFAULT ''"),
            ('masterclass_meeting_url', "varchar(500) NOT NULL DEFAULT ''"),
            ('masterclass_scheduled_at', f'{scheduled_type} NULL'),
            ('masterclass_duration_minutes', 'integer NOT NULL DEFAULT 60'),
        ]
        with connection.cursor() as cursor:
            for name, sql_type in additions:
                if name not in columns:
                    cursor.execute(f'ALTER TABLE catalog_course ADD COLUMN {name} {sql_type}')

    if 'assessments_quiz' in tables:
        columns = _columns(connection, 'assessments_quiz')
        if 'show_correct_answers' not in columns:
            with connection.cursor() as cursor:
                cursor.execute(
                    'ALTER TABLE assessments_quiz ADD COLUMN show_correct_answers boolean NOT NULL DEFAULT TRUE'
                )


def noop_reverse(apps, schema_editor):
    # No eliminamos columnas al revertir: podrían contener configuración real del profesor.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('tenancy', '0006_email_bypass_certificate_style'),
    ]

    operations = [
        migrations.RunPython(ensure_course_and_quiz_columns, noop_reverse),
    ]
