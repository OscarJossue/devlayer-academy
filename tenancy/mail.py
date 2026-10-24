from email.message import MIMEPart
import mimetypes

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.mail import EmailMultiAlternatives
from django.core.mail.backends.smtp import EmailBackend


def academy_uses_custom_smtp(academy):
    return bool(academy and academy.smtp_configured)


def _platform_record():
    """Devuelve la fila global si la tabla ya existe.

    Antes de ejecutar la migración la tabla puede no existir; en ese único caso
    mantenemos compatibilidad con el SMTP histórico del entorno.
    """
    try:
        from .models import PlatformEmailSettings
        return PlatformEmailSettings.objects.filter(pk=1).first()
    except Exception:
        return None


def _platform_settings():
    obj = _platform_record()
    return obj if obj and obj.configured else None


def platform_mail_available():
    record = _platform_record()
    if record is not None:
        return bool(record.configured)
    return bool(getattr(settings, 'SMTP_CONFIGURED', False))


def platform_sender():
    record = _platform_record()
    if record is not None:
        return record.sender if record.configured else ''
    return getattr(settings, 'DEFAULT_FROM_EMAIL', '') or getattr(settings, 'EMAIL_HOST_USER', '')


def platform_email_connection(fail_silently=False):
    record = _platform_record()
    if record is not None:
        if not record.configured:
            raise RuntimeError('El SMTP global de DevLayer Studio está deshabilitado o incompleto.')
        return EmailBackend(
            host=record.smtp_host,
            port=record.smtp_port,
            username=record.smtp_username,
            password=record.smtp_password,
            use_tls=record.smtp_use_tls,
            use_ssl=record.smtp_use_ssl,
            timeout=20,
            fail_silently=fail_silently,
        )
    if not getattr(settings, 'SMTP_CONFIGURED', False):
        raise RuntimeError('El servicio de correo predeterminado de DevLayer Studio no está disponible.')
    return EmailBackend(
        host=settings.EMAIL_HOST,
        port=settings.EMAIL_PORT,
        username=settings.EMAIL_HOST_USER,
        password=settings.EMAIL_HOST_PASSWORD,
        use_tls=settings.EMAIL_USE_TLS,
        use_ssl=settings.EMAIL_USE_SSL,
        timeout=getattr(settings, 'EMAIL_TIMEOUT', 20),
        fail_silently=fail_silently,
    )


def academy_mail_available(academy=None):
    return bool(academy_uses_custom_smtp(academy) or platform_mail_available())


def academy_sender(academy=None):
    if academy_uses_custom_smtp(academy):
        return academy.smtp_sender
    return platform_sender()


def academy_email_connection(academy, fail_silently=False):
    if academy_uses_custom_smtp(academy):
        return EmailBackend(
            host=academy.smtp_host,
            port=academy.smtp_port,
            username=academy.smtp_username,
            password=academy.smtp_password,
            use_tls=academy.smtp_use_tls,
            use_ssl=academy.smtp_use_ssl,
            timeout=20,
            fail_silently=fail_silently,
        )
    return platform_email_connection(fail_silently=fail_silently)


def attach_brand_logo_image(email, academy):
    """Adjunta el logo como imagen inline compatible con Django 6+."""
    try:
        filename = 'devlayer-studio.png'
        if academy and academy.logo:
            academy.logo.open('rb')
            content = academy.logo.read()
            filename = academy.logo.name.rsplit('/', 1)[-1] or 'academy-logo.png'
            academy.logo.close()
        else:
            default_path = finders.find('img/devlayer-studio.png')
            if not default_path:
                return False
            with open(default_path, 'rb') as handle:
                content = handle.read()

        guessed_type, _ = mimetypes.guess_type(filename)
        subtype = guessed_type.split('/', 1)[1] if guessed_type and guessed_type.startswith('image/') else 'png'
        inline_image = MIMEPart()
        inline_image.set_content(
            content,
            maintype='image',
            subtype=subtype,
            disposition='inline',
            cid='<academy-logo>',
            filename=filename,
        )
        email.attach(inline_image)
        return True
    except Exception:
        return False


attach_brand_logo = attach_brand_logo_image


def send_platform_mail(subject, message, recipients, fail_silently=False, html_message=None):
    connection = platform_email_connection(fail_silently=fail_silently)
    email = EmailMultiAlternatives(
        subject=subject,
        body=message,
        from_email=platform_sender(),
        to=list(recipients),
        connection=connection,
    )
    if html_message:
        email.attach_alternative(html_message, 'text/html')
    return email.send()


def send_academy_mail(academy, subject, message, recipients, fail_silently=False, html_message=None, attach_brand_logo=False):
    connection = academy_email_connection(academy, fail_silently=fail_silently)
    email = EmailMultiAlternatives(
        subject=subject,
        body=message,
        from_email=academy_sender(academy),
        to=list(recipients),
        connection=connection,
    )
    if html_message:
        if attach_brand_logo:
            attach_brand_logo_image(email, academy)
        email.attach_alternative(html_message, 'text/html')
    return email.send()
