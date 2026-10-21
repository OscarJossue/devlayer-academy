from email.message import MIMEPart
import mimetypes

from django.contrib.staticfiles import finders
from django.core.mail import EmailMultiAlternatives
from django.core.mail.backends.smtp import EmailBackend


def academy_email_connection(academy, fail_silently=False):
    if not academy or not academy.smtp_configured:
        raise RuntimeError('El SMTP de esta academia todavía no está configurado.')
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


def attach_brand_logo_image(email, academy):
    """Adjunta el logo como imagen inline compatible con Django 6+.

    El HTML de los correos referencia el contenido como ``cid:academy-logo``.
    Django 6 eliminó ``mixed_subtype`` y recomienda adjuntos ``MIMEPart``.
    """
    try:
        filename = 'devlayer-studio.png'
        if academy.logo:
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
        if guessed_type and guessed_type.startswith('image/'):
            subtype = guessed_type.split('/', 1)[1]
        else:
            subtype = 'png'

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



# Alias público usado por recuperación de contraseña y otros flujos.
attach_brand_logo = attach_brand_logo_image

def send_academy_mail(academy, subject, message, recipients, fail_silently=False, html_message=None, attach_brand_logo=False):
    # Django 6.1 ya no permite pasar fail_silently a EmailMessage.send()
    # cuando el mensaje ya tiene una conexión explícita. La política de error
    # debe configurarse en el backend SMTP y luego send() se llama sin argumentos.
    connection = academy_email_connection(academy, fail_silently=fail_silently)
    email = EmailMultiAlternatives(
        subject=subject,
        body=message,
        from_email=academy.smtp_sender,
        to=list(recipients),
        connection=connection,
    )
    if html_message:
        if attach_brand_logo:
            attach_brand_logo_image(email, academy)
        email.attach_alternative(html_message, 'text/html')
    return email.send()
