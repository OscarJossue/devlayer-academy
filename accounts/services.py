from django.core import signing
from django.templatetags.static import static
from django.urls import reverse
from django.utils.html import escape

from tenancy.mail import send_academy_mail
from tenancy.services import membership_for_user

SALT = 'devlayer-email-verification'


def verification_token(user, academy):
    return signing.dumps(
        {'uid': str(user.pk), 'email': user.email, 'academy': academy.slug},
        salt=SALT,
        compress=True,
    )


def _academy_logo_url(request, academy):
    if academy.logo:
        return request.build_absolute_uri(reverse('tenancy:academy_logo', args=[academy.slug]))
    return request.build_absolute_uri(static('img/devlayer-studio.png'))


def _academy_email_html(request, academy, title, intro, action_label=None, action_url=None, footer=None):
    brand = escape(academy.brand_color or '#1458D6')
    logo_url = 'cid:academy-logo'
    academy_name = escape(academy.name)
    button = ''
    if action_label and action_url:
        button = (
            f'<p style="margin:28px 0 18px">'
            f'<a href="{escape(action_url)}" style="display:inline-block;background:{brand};color:#fff;'
            'text-decoration:none;font-weight:700;padding:12px 18px;border-radius:8px;font-family:Arial,sans-serif">'
            f'{escape(action_label)}</a></p>'
        )
    footer_text = escape(footer or f'Este correo fue enviado por {academy.name}.')
    return f'''<!doctype html><html><body style="margin:0;background:#f5f7fb;padding:24px;font-family:Arial,sans-serif;color:#172033">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center">
<table role="presentation" width="100%" style="max-width:620px;background:#fff;border:1px solid #e4e8ef;border-radius:14px;overflow:hidden" cellspacing="0" cellpadding="0">
<tr><td style="height:5px;background:{brand}"></td></tr>
<tr><td style="padding:28px 30px 8px"><img src="{logo_url}" alt="{academy_name}" style="display:block;max-width:180px;max-height:64px;object-fit:contain"></td></tr>
<tr><td style="padding:8px 30px 30px"><p style="margin:0 0 8px;font-size:12px;font-weight:700;color:{brand};text-transform:uppercase;letter-spacing:.08em">{academy_name}</p>
<h1 style="margin:0 0 16px;font-size:24px;line-height:1.2">{escape(title)}</h1>
<div style="font-size:15px;line-height:1.65;color:#566176">{intro}</div>{button}
<p style="margin:24px 0 0;padding-top:18px;border-top:1px solid #edf0f4;font-size:12px;line-height:1.55;color:#8791a3">{footer_text}</p></td></tr>
</table></td></tr></table></body></html>'''


def send_verification_email(request, user, academy=None):
    academy = academy or getattr(request, 'academy', None)
    if not academy:
        membership = membership_for_user(user)
        academy = membership.academy if membership else None
    if not academy:
        raise RuntimeError('No se pudo determinar la academia para enviar el correo.')
    if not academy.smtp_configured:
        raise RuntimeError('El SMTP de esta academia todavía no está configurado.')
    token = verification_token(user, academy)
    url = request.build_absolute_uri(reverse('tenancy:academy_verify_email', args=[academy.slug, token]))
    name = escape(user.display_name)
    html = _academy_email_html(
        request,
        academy,
        'Verifica tu correo',
        f'<p>Hola <strong>{name}</strong>.</p><p>Confirma tu dirección de correo para proteger tu cuenta y completar tu perfil. Puedes ingresar a la academia mientras verificas; el acceso al contenido de cada curso depende de tu matrícula.</p>',
        action_label='Verificar mi correo',
        action_url=url,
        footer='El enlace de verificación vence en 24 horas. Si no solicitaste esta cuenta, puedes ignorar este mensaje.',
    )
    return send_academy_mail(
        academy,
        subject=f'Verifica tu cuenta · {academy.name}',
        message=(
            f'Hola {user.display_name},\n\n'
            f'Confirma tu correo para continuar con tu registro en {academy.name}:\n{url}\n\n'
            'Puedes ingresar a la academia mientras verificas; el acceso al contenido de cada curso depende de tu matrícula. '
            'Este enlace vence en 24 horas.'
        ),
        recipients=[user.email],
        fail_silently=False,
        html_message=html,
        attach_brand_logo=True,
    )


def send_membership_approved_email(request, user, academy):
    if not academy.smtp_configured:
        return 0
    login_url = request.build_absolute_uri(reverse('tenancy:academy_login', args=[academy.slug]))
    html = _academy_email_html(
        request,
        academy,
        'Tu cuenta está habilitada',
        f'<p>Hola <strong>{escape(user.display_name)}</strong>.</p><p>Tu cuenta en <strong>{escape(academy.name)}</strong> está habilitada. Ya puedes iniciar sesión con tu correo.</p>',
        action_label='Ingresar a la academia',
        action_url=login_url,
    )
    return send_academy_mail(
        academy,
        subject=f'Cuenta habilitada · {academy.name}',
        message=(
            f'Hola {user.display_name},\n\n'
            f'Tu cuenta en {academy.name} está habilitada.\n'
            f'Puedes iniciar sesión aquí:\n{login_url}\n\n'
            f'{academy.name}'
        ),
        recipients=[user.email],
        fail_silently=True,
        html_message=html,
        attach_brand_logo=True,
    )


def send_new_registration_notice(request, user, academy):
    if not academy.smtp_configured:
        return 0
    from accounts.models import User
    from tenancy.models import AcademyMembership
    owner_ids = AcademyMembership.objects.filter(
        academy=academy,
        role=AcademyMembership.Role.OWNER,
        status=AcademyMembership.Status.ACTIVE,
    ).values_list('user_id', flat=True)
    recipients = list(User.objects.filter(pk__in=owner_ids, is_active=True).values_list('email', flat=True))
    if not recipients:
        return 0
    users_url = request.build_absolute_uri('/admin/usuarios/')
    html = _academy_email_html(
        request,
        academy,
        'Nuevo estudiante registrado',
        f'<p><strong>{escape(user.display_name)}</strong> se registró en tu academia.</p><p>Correo: {escape(user.email)}</p><p>La cuenta ya puede explorar el catálogo. El acceso al contenido de los cursos se habilita cuando apruebas su pago o matrícula.</p>',
        action_label='Ver usuarios',
        action_url=users_url,
    )
    return send_academy_mail(
        academy,
        subject=f'Nuevo estudiante registrado · {academy.name}',
        message=(
            f'Nuevo estudiante registrado en {academy.name}.\n\n'
            f'Estudiante: {user.display_name}\nCorreo: {user.email}\n\n'
            f'Ver usuarios: {users_url}'
        ),
        recipients=recipients,
        fail_silently=True,
        html_message=html,
        attach_brand_logo=True,
    )
