from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('tenancy', '0008_professor_student_payment_permission'),
    ]

    operations = [
        migrations.AddField(
            model_name='academy',
            name='support_title',
            field=models.CharField(blank=True, default='Soporte de la academia', max_length=90, verbose_name='Nombre del panel de soporte'),
        ),
        migrations.AddField(
            model_name='academy',
            name='support_whatsapp_1_label',
            field=models.CharField(blank=True, max_length=60, verbose_name='Etiqueta del WhatsApp 1'),
        ),
        migrations.AddField(
            model_name='academy',
            name='support_whatsapp_1_number',
            field=models.CharField(blank=True, max_length=30, verbose_name='WhatsApp 1'),
        ),
        migrations.AddField(
            model_name='academy',
            name='support_whatsapp_2_label',
            field=models.CharField(blank=True, max_length=60, verbose_name='Etiqueta del WhatsApp 2'),
        ),
        migrations.AddField(
            model_name='academy',
            name='support_whatsapp_2_number',
            field=models.CharField(blank=True, max_length=30, verbose_name='WhatsApp 2'),
        ),
    ]
