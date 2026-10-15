import os
from django.core.management.base import BaseCommand
from accounts.models import User

class Command(BaseCommand):
    help = 'Crea el superadmin inicial si no existe.'

    def handle(self, *args, **options):
        email = os.getenv('DJANGO_SUPERUSER_EMAIL', '').strip().lower()
        password = os.getenv('DJANGO_SUPERUSER_PASSWORD', '')
        if not email or not password:
            self.stdout.write('Superadmin omitido: variables no configuradas.')
            return
        user = User.objects.filter(email=email).first()
        if user:
            if not user.is_superuser:
                user.is_staff = True
                user.is_superuser = True
                user.role = User.Role.SUPERADMIN
                user.email_verified = True
                user.save()
            self.stdout.write(f'Superadmin existente: {email}')
            return
        User.objects.create_superuser(email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f'Superadmin creado: {email}'))
