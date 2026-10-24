from django.db import migrations, models


def configure_horizonte_accounting(apps, schema_editor):
    Academy = apps.get_model('tenancy', 'Academy')
    Academy.objects.filter(slug='academia-horizonte').update(
        support_whatsapp_2_label='Contabilidad',
        support_whatsapp_2_number='593985721899',
        payment_whatsapp_enabled=True,
        payment_whatsapp_number='593985721899',
    )


def reverse_horizonte_accounting(apps, schema_editor):
    Academy = apps.get_model('tenancy', 'Academy')
    Academy.objects.filter(slug='academia-horizonte', support_whatsapp_2_number='593985721899').update(
        support_whatsapp_2_label='', support_whatsapp_2_number='',
    )


class Migration(migrations.Migration):
    dependencies = [('tenancy', '0009_academy_support_whatsapp')]

    operations = [
        migrations.AddField(model_name='academy', name='payment_paypal_enabled', field=models.BooleanField(default=False, verbose_name='Aceptar PayPal')),
        migrations.AddField(model_name='academy', name='payment_paypal_email', field=models.EmailField(blank=True, max_length=254, verbose_name='Correo de PayPal')),
        migrations.AddField(model_name='academy', name='payment_paypal_url', field=models.URLField(blank=True, verbose_name='Enlace de PayPal')),
        migrations.AddField(model_name='academy', name='payment_payphone_enabled', field=models.BooleanField(default=False, verbose_name='Aceptar PayPhone')),
        migrations.AddField(model_name='academy', name='payment_payphone_reference', field=models.CharField(blank=True, max_length=120, verbose_name='Dato de PayPhone')),
        migrations.AddField(model_name='academy', name='payment_payphone_url', field=models.URLField(blank=True, verbose_name='Enlace de PayPhone')),
        migrations.AddField(model_name='academy', name='payment_card_enabled', field=models.BooleanField(default=False, verbose_name='Aceptar tarjeta mediante link solicitado por WhatsApp')),
        migrations.AddField(model_name='academy', name='payment_card_instructions', field=models.CharField(blank=True, default='Solicita tu link de pago por WhatsApp y completa el pago con tarjeta.', max_length=220, verbose_name='Indicaciones para tarjeta')),
        migrations.AddField(model_name='academy', name='payment_link_1_enabled', field=models.BooleanField(default=False, verbose_name='Habilitar link de pago 1')),
        migrations.AddField(model_name='academy', name='payment_link_1_label', field=models.CharField(blank=True, max_length=80, verbose_name='Nombre del link de pago 1')),
        migrations.AddField(model_name='academy', name='payment_link_1_url', field=models.URLField(blank=True, verbose_name='URL del link de pago 1')),
        migrations.AddField(model_name='academy', name='payment_link_2_enabled', field=models.BooleanField(default=False, verbose_name='Habilitar link de pago 2')),
        migrations.AddField(model_name='academy', name='payment_link_2_label', field=models.CharField(blank=True, max_length=80, verbose_name='Nombre del link de pago 2')),
        migrations.AddField(model_name='academy', name='payment_link_2_url', field=models.URLField(blank=True, verbose_name='URL del link de pago 2')),
        migrations.AlterField(model_name='academy', name='payment_whatsapp_enabled', field=models.BooleanField(default=False, verbose_name='Aceptar soporte/reporte de pago por WhatsApp')),
        migrations.RunPython(configure_horizonte_accounting, reverse_horizonte_accounting),
    ]
