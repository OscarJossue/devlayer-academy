from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('tenancy', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='academy',
            name='brand_color',
            field=models.CharField(default='#1458D6', max_length=7, verbose_name='Color principal'),
        ),
        migrations.AddField(
            model_name='academy',
            name='logo',
            field=models.ImageField(blank=True, null=True, upload_to='academy_branding/%Y/%m/'),
        ),
        migrations.AddField(
            model_name='academy',
            name='public_description',
            field=models.TextField(blank=True, verbose_name='Descripción pública'),
        ),
        migrations.AddField(
            model_name='academy',
            name='tagline',
            field=models.CharField(blank=True, max_length=160, verbose_name='Frase principal'),
        ),
    ]
