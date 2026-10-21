from django.core.management.base import BaseCommand, CommandError

from tenancy.mail import send_academy_mail
from tenancy.models import Academy


class Command(BaseCommand):
    help = 'Prueba el SMTP configurado por una academia. No utiliza un SMTP global.'

    def add_arguments(self, parser):
        parser.add_argument('academy_slug', help='Slug de la academia, por ejemplo dev-layer')
        parser.add_argument('recipient', nargs='?', help='Correo destino. Si se omite usa el correo remitente de la academia.')

    def handle(self, *args, **options):
        academy = Academy.objects.filter(slug=options['academy_slug']).first()
        if not academy:
            raise CommandError('No existe una academia con ese slug.')
        if not academy.smtp_configured:
            raise CommandError('El SMTP de esta academia está incompleto o deshabilitado.')
        recipient = (options.get('recipient') or academy.smtp_from_email or '').strip()
        if not recipient:
            raise CommandError('Indica un correo destino o configura el correo remitente de la academia.')
        mode = 'SSL' if academy.smtp_use_ssl else ('STARTTLS' if academy.smtp_use_tls else 'sin cifrado')
        self.stdout.write(
            f'Probando SMTP de {academy.name}: {academy.smtp_host}:{academy.smtp_port} · {mode} · remitente {academy.smtp_from_email}'
        )
        try:
            sent = send_academy_mail(
                academy,
                subject=f'Prueba SMTP · {academy.name}',
                message='El SMTP independiente de esta academia funciona correctamente.',
                recipients=[recipient],
                fail_silently=False,
            )
        except Exception as exc:
            raise CommandError(f'Falló el SMTP de {academy.name}: {exc}') from exc
        if sent != 1:
            raise CommandError(f'El backend SMTP respondió sin error, pero devolvió {sent}.')
        self.stdout.write(self.style.SUCCESS(f'Correo enviado correctamente a {recipient}.'))
