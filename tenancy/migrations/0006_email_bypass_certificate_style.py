from django.db import migrations, models


def ensure_course_certificate_columns(apps, schema_editor):
    """Compatibilidad con las apps cuya 0001 se genera al arrancar Docker.

    En instalaciones existentes, catalog.0001 ya figura como aplicada pero el archivo
    se regenera con el modelo actual. Por eso garantizamos físicamente las columnas
    nuevas sin depender de una catalog.0002 que no tendría una 0001 versionada en disco.
    En instalaciones nuevas, si catalog_course todavía no existe, la 0001 generada la
    creará después con estos campos y esta función simplemente no hace nada.
    """
    connection = schema_editor.connection
    table_names = set(connection.introspection.table_names())
    if 'catalog_course' not in table_names:
        return

    with connection.cursor() as cursor:
        columns = {
            col.name
            for col in connection.introspection.get_table_description(cursor, 'catalog_course')
        }
        definitions = {
            'certificate_enabled': "boolean NOT NULL DEFAULT TRUE",
            'certificate_style_mode': "varchar(20) NOT NULL DEFAULT 'ACADEMY'",
            'certificate_custom_title': "varchar(180) NOT NULL DEFAULT ''",
            'certificate_custom_subtitle': "varchar(180) NOT NULL DEFAULT ''",
            'certificate_custom_body': "varchar(240) NOT NULL DEFAULT ''",
            'certificate_custom_accent_color': "varchar(7) NOT NULL DEFAULT ''",
            'certificate_custom_background_color': "varchar(7) NOT NULL DEFAULT ''",
            'certificate_custom_text_color': "varchar(7) NOT NULL DEFAULT ''",
            'certificate_custom_signature_name': "varchar(160) NOT NULL DEFAULT ''",
            'certificate_custom_signature_role': "varchar(160) NOT NULL DEFAULT ''",
            'certificate_custom_signature_image': "varchar(100) NULL",
            'certificate_custom_footer': "varchar(240) NOT NULL DEFAULT ''",
            'certificate_custom_show_qr': "boolean NOT NULL DEFAULT TRUE",
            'certificate_custom_show_logo': "boolean NOT NULL DEFAULT TRUE",
        }
        qn = schema_editor.quote_name
        for name, definition in definitions.items():
            if name not in columns:
                cursor.execute(
                    f'ALTER TABLE {qn("catalog_course")} ADD COLUMN {qn(name)} {definition}'
                )


def noop_reverse(apps, schema_editor):
    # No eliminamos columnas al revertir: pueden contener diseños ya emitidos.
    pass


class Migration(migrations.Migration):
    dependencies = [('tenancy', '0005_payment_settings_bank_binding_fix')]

    operations = [
        migrations.AddField(
            model_name='academy',
            name='allow_unverified_approvals',
            field=models.BooleanField(default=False, verbose_name='Permitir aprobaciones sin verificar correo'),
        ),
        migrations.AddField(
            model_name='academymembership',
            name='email_verification_bypassed',
            field=models.BooleanField(default=False, verbose_name='Autorizado sin verificación de correo'),
        ),
        migrations.AddField(
            model_name='academy',
            name='certificate_title',
            field=models.CharField(default='Certificado de finalización', max_length=180, verbose_name='Título del certificado'),
        ),
        migrations.AddField(
            model_name='academy',
            name='certificate_subtitle',
            field=models.CharField(default='Se certifica que', max_length=180, verbose_name='Texto previo al estudiante'),
        ),
        migrations.AddField(
            model_name='academy',
            name='certificate_body',
            field=models.CharField(default='ha completado satisfactoriamente el curso', max_length=240, verbose_name='Texto previo al curso'),
        ),
        migrations.AddField(
            model_name='academy',
            name='certificate_accent_color',
            field=models.CharField(blank=True, default='', max_length=7, verbose_name='Color de acento del certificado'),
        ),
        migrations.AddField(
            model_name='academy',
            name='certificate_background_color',
            field=models.CharField(default='#FFFFFF', max_length=7, verbose_name='Fondo del certificado'),
        ),
        migrations.AddField(
            model_name='academy',
            name='certificate_text_color',
            field=models.CharField(default='#172033', max_length=7, verbose_name='Color del texto del certificado'),
        ),
        migrations.AddField(
            model_name='academy',
            name='certificate_signature_name',
            field=models.CharField(blank=True, max_length=160, verbose_name='Nombre de la firma'),
        ),
        migrations.AddField(
            model_name='academy',
            name='certificate_signature_role',
            field=models.CharField(blank=True, max_length=160, verbose_name='Cargo de la firma'),
        ),
        migrations.AddField(
            model_name='academy',
            name='certificate_signature_image',
            field=models.ImageField(blank=True, null=True, upload_to='academy_certificates/signatures/%Y/%m/', verbose_name='Imagen de firma'),
        ),
        migrations.AddField(
            model_name='academy',
            name='certificate_footer',
            field=models.CharField(blank=True, default='Certificado verificable digitalmente.', max_length=240, verbose_name='Texto inferior'),
        ),
        migrations.AddField(
            model_name='academy',
            name='certificate_show_qr',
            field=models.BooleanField(default=True, verbose_name='Mostrar código QR'),
        ),
        migrations.AddField(
            model_name='academy',
            name='certificate_show_logo',
            field=models.BooleanField(default=True, verbose_name='Mostrar logo de la academia'),
        ),
        migrations.RunPython(ensure_course_certificate_columns, noop_reverse),
    ]
