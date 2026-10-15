from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.core import signing
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from .forms import RegisterForm
from .models import User
from .services import SALT, send_verification_email


def role_home_url(user):
    if user.is_superuser or user.role == User.Role.SUPERADMIN:
        return reverse('superadmin:dashboard')
    if user.role in {User.Role.PROFESSOR, User.Role.ADMIN}:
        return reverse('catalog:professor_dashboard')
    return reverse('learning:dashboard')


class AcademyLoginView(auth_views.LoginView):
    template_name = 'accounts/login.html'

    def get_success_url(self):
        requested = self.get_redirect_url()
        return requested or role_home_url(self.request.user)


def register(request):
    if request.user.is_authenticated:
        return redirect(role_home_url(request.user))
    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save(commit=False)
        user.role = User.Role.STUDENT
        user.email_verified = False
        user.save()
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        try:
            send_verification_email(request, user)
            messages.success(request, 'Cuenta creada. Revisa tu correo para verificarla.')
        except Exception:
            messages.warning(request, 'La cuenta fue creada, pero el servidor SMTP no pudo enviar el correo. Revisa la configuración SMTP y usa reenviar.')
        return redirect('accounts:verification_pending')
    return render(request, 'accounts/register.html', {'form': form})


def verification_pending(request):
    return render(request, 'accounts/verification_pending.html')


def resend_verification(request):
    if not request.user.is_authenticated:
        return redirect('accounts:login')
    if request.user.email_verified:
        return redirect(role_home_url(request.user))
    if request.method == 'POST':
        try:
            send_verification_email(request, request.user)
            messages.success(request, 'Nuevo correo de verificación enviado.')
        except Exception:
            messages.error(request, 'No se pudo enviar el correo. Revisa la configuración SMTP.')
    return redirect('accounts:verification_pending')


def verify_email(request, token):
    try:
        data = signing.loads(token, salt=SALT, max_age=60 * 60 * 24)
    except signing.BadSignature:
        messages.error(request, 'El enlace de verificación es inválido o venció.')
        return redirect('accounts:verification_pending')
    user = get_object_or_404(User, pk=data['uid'], email=data['email'])
    if not user.email_verified:
        user.email_verified = True
        user.save(update_fields=['email_verified'])
    messages.success(request, 'Correo verificado correctamente.')
    return redirect(role_home_url(user))


class AcademyPasswordResetView(auth_views.PasswordResetView):
    """Recuperación de contraseña usando únicamente el SMTP real configurado."""

    def form_valid(self, form):
        if not getattr(settings, 'SMTP_CONFIGURED', False):
            messages.error(
                self.request,
                'El envío de correo todavía no está configurado. Configura el SMTP de salida en .env.'
            )
            return redirect('accounts:password_reset')
        try:
            return super().form_valid(form)
        except Exception:
            messages.error(
                self.request,
                'No se pudo conectar con el servidor SMTP. Revisa host, puerto, usuario, contraseña y TLS/SSL.'
            )
            return redirect('accounts:password_reset')
