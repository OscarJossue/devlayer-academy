from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Prueba el SMTP real de salida enviando un correo a una dirección indicada.'

    def add_arguments(self, parser):
        parser.add_argument('recipient', help='Correo que recibirá la prueba SMTP')

    def handle(self, *args, **options):
        recipient = options['recipient'].strip()
        if not getattr(settings, 'SMTP_CONFIGURED', False):
            raise CommandError(
                'SMTP incompleto. Configura EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, '
                'EMAIL_HOST_PASSWORD y DEFAULT_FROM_EMAIL en .env.'
            )

        mode = 'SSL' if settings.EMAIL_USE_SSL else ('STARTTLS' if settings.EMAIL_USE_TLS else 'sin cifrado SMTP')
        self.stdout.write(
            f'Probando {settings.EMAIL_HOST}:{settings.EMAIL_PORT} · {mode} · remitente {settings.DEFAULT_FROM_EMAIL}'
        )
        try:
            sent = send_mail(
                subject='Prueba SMTP · Devlayer Academy',
                message=(
                    'Este correo confirma que Devlayer Academy puede enviar correo mediante '
                    'el servidor SMTP configurado.\n\nNo se utiliza ninguna bandeja local.'
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                fail_silently=False,
            )
        except Exception as exc:
            raise CommandError(f'Falló el envío SMTP: {exc}') from exc

        if sent != 1:
            raise CommandError(f'El backend SMTP respondió sin error, pero send_mail devolvió {sent}.')
        self.stdout.write(self.style.SUCCESS(f'Correo SMTP enviado correctamente a {recipient}.'))
