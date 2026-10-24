from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('tenancy', '0007_course_masterclass_quiz_settings'),
    ]

    operations = [
        migrations.AddField(
            model_name='academymembership',
            name='can_manage_student_payments',
            field=models.BooleanField(
                default=False,
                verbose_name='Puede gestionar estudiantes y pagos de sus cursos',
            ),
        ),
    ]
