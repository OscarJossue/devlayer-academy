from django.db import migrations


def _columns(connection, table):
    with connection.cursor() as cursor:
        return {item.name for item in connection.introspection.get_table_description(cursor, table)}


def ensure_quiz_timing_columns(apps, schema_editor):
    connection = schema_editor.connection
    tables = set(connection.introspection.table_names())

    if 'assessments_quiz' in tables:
        columns = _columns(connection, 'assessments_quiz')
        additions = [
            ('time_mode', "varchar(20) NOT NULL DEFAULT 'NONE'"),
            ('time_limit_minutes', 'integer NULL'),
        ]
        with connection.cursor() as cursor:
            for name, sql_type in additions:
                if name not in columns:
                    cursor.execute(f'ALTER TABLE assessments_quiz ADD COLUMN {name} {sql_type}')

    if 'assessments_quizattempt' in tables:
        columns = _columns(connection, 'assessments_quizattempt')
        additions = [
            ('time_mode_snapshot', "varchar(20) NOT NULL DEFAULT 'NONE'"),
            ('time_limit_minutes_snapshot', 'integer NULL'),
            ('elapsed_seconds', 'integer NULL'),
            ('overtime_seconds', 'integer NOT NULL DEFAULT 0'),
            ('timed_out', 'boolean NOT NULL DEFAULT FALSE'),
        ]
        with connection.cursor() as cursor:
            for name, sql_type in additions:
                if name not in columns:
                    cursor.execute(f'ALTER TABLE assessments_quizattempt ADD COLUMN {name} {sql_type}')

            # Los intentos existentes conservan una fotografía coherente de la
            # configuración vigente al momento de desplegar esta mejora.
            cursor.execute(
                """
                UPDATE assessments_quizattempt
                SET time_mode_snapshot = COALESCE(
                    (SELECT q.time_mode FROM assessments_quiz q WHERE q.id = assessments_quizattempt.quiz_id),
                    'NONE'
                )
                WHERE time_mode_snapshot = 'NONE'
                """
            )
            cursor.execute(
                """
                UPDATE assessments_quizattempt
                SET time_limit_minutes_snapshot = (
                    SELECT q.time_limit_minutes FROM assessments_quiz q WHERE q.id = assessments_quizattempt.quiz_id
                )
                WHERE time_limit_minutes_snapshot IS NULL
                """
            )


def noop_reverse(apps, schema_editor):
    # Conservamos las columnas al revertir para no perder tiempos académicos.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('tenancy', '0010_academy_payment_channels'),
    ]

    operations = [
        migrations.RunPython(ensure_quiz_timing_columns, noop_reverse),
    ]
