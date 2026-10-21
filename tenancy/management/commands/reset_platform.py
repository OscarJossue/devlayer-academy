import os

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Vacía la plataforma. Puede dejar solo la cuenta maestra o cargar un escenario demo controlado.'

    def add_arguments(self, parser):
        parser.add_argument('--confirm', action='store_true', help='Confirma el borrado total de datos.')
        parser.add_argument('--demo', action='store_true', help='Después del reset crea 3 planes, 3 academias demo y 2 cursos completos en Academia Horizonte.')

    def handle(self, *args, **options):
        if not options.get('confirm'):
            raise CommandError('Operación cancelada. Usa: python manage.py reset_platform --confirm [--demo]')

        email = os.getenv('DJANGO_SUPERUSER_EMAIL', '').strip().lower()
        password = os.getenv('DJANGO_SUPERUSER_PASSWORD', '')
        if not email or not password:
            raise CommandError('Configura DJANGO_SUPERUSER_EMAIL y DJANGO_SUPERUSER_PASSWORD antes de resetear.')

        self.stdout.write(self.style.WARNING('Eliminando academias, usuarios, cursos, pagos, certificados y demás datos...'))
        call_command('flush', interactive=False, verbosity=0)
        call_command('create_initial_superadmin')

        if options.get('demo'):
            call_command('seed_platform_demo')
            self.stdout.write(self.style.SUCCESS(f'Base reiniciada. Cuenta maestra: {email}. Se cargaron 3 planes, 3 academias demo y el escenario académico completo de Academia Horizonte.'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Base limpia. Única cuenta: {email} (administrador maestro del sistema).'))
