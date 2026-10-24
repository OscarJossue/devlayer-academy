from django.db import migrations, models
import core.fields


class Migration(migrations.Migration):
    dependencies = [
        ('tenancy', '0011_quiz_timing_academic_sync'),
    ]

    operations = [
        migrations.CreateModel(
            name='PlatformEmailSettings',
            fields=[
                ('id', models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ('is_enabled', models.BooleanField(default=False, verbose_name='Correo global habilitado')),
                ('smtp_host', models.CharField(blank=True, max_length=255, verbose_name='Servidor SMTP')),
                ('smtp_port', models.PositiveIntegerField(default=587, verbose_name='Puerto SMTP')),
                ('smtp_username', models.CharField(blank=True, max_length=255, verbose_name='Usuario SMTP')),
                ('smtp_password', core.fields.EncryptedTextField(blank=True, verbose_name='Contraseña SMTP')),
                ('smtp_use_tls', models.BooleanField(default=True, verbose_name='Usar STARTTLS')),
                ('smtp_use_ssl', models.BooleanField(default=False, verbose_name='Usar SSL')),
                ('smtp_from_email', models.EmailField(blank=True, max_length=254, verbose_name='Correo remitente')),
                ('smtp_from_name', models.CharField(blank=True, default='DevLayer Studio', max_length=160, verbose_name='Nombre remitente')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Correo global de la plataforma',
                'verbose_name_plural': 'Correo global de la plataforma',
            },
        ),
    ]
