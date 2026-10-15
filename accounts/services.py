from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.urls import reverse

SALT = 'devlayer-email-verification'


def verification_token(user):
    return signing.dumps({'uid': str(user.pk), 'email': user.email}, salt=SALT, compress=True)


def assert_smtp_configured():
    if not getattr(settings, 'SMTP_CONFIGURED', False):
        raise RuntimeError(
            'SMTP no configurado. Completa EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, '
            'EMAIL_HOST_PASSWORD y DEFAULT_FROM_EMAIL en .env.'
        )


def send_verification_email(request, user):
    assert_smtp_configured()
    token = verification_token(user)
    url = request.build_absolute_uri(reverse('accounts:verify_email', args=[token]))
    return send_mail(
        subject='Verifica tu cuenta · Devlayer Academy',
        message=(
            f'Hola {user.display_name},\n\n'
            f'Confirma tu correo para activar tu cuenta:\n{url}\n\n'
            'Este enlace vence en 24 horas.'
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )
