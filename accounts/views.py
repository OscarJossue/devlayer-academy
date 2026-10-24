import logging

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth import views as auth_views
from django.core import signing
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_POST

from tenancy.models import Academy, AcademyMembership
from tenancy.mail import academy_mail_available, academy_sender
from tenancy.services import academy_has_available_seat, bind_user, membership_for_user, scope_courses
from .forms import AcademyPasswordResetForm, EmailAuthenticationForm, RegisterForm
from .models import User
from .services import SALT, send_new_registration_notice, send_verification_email


logger = logging.getLogger(__name__)


def role_home_url(user, academy):
    if user.is_superuser:
        return reverse('tenancy:system_dashboard')
    membership = membership_for_user(user, academy=academy)
    if not membership:
        return reverse('tenancy:academy_login', args=[academy.slug])
    if membership.status != AcademyMembership.Status.ACTIVE:
        return reverse('tenancy:membership_pending', args=[academy.slug])
    if membership.role == AcademyMembership.Role.OWNER:
        return reverse('superadmin:dashboard')
    if membership.role in {AcademyMembership.Role.PROFESSOR, AcademyMembership.Role.ADMIN}:
        return reverse('catalog:professor_dashboard')
    return reverse('learning:dashboard')




@require_POST
def logout_view(request):
    """Cierra por completo la sesión y vuelve al acceso de la academia actual."""
    academy_slug = (request.session.get('academy_slug') or '').strip()
    logout(request)
    academy = Academy.objects.filter(slug=academy_slug, is_active=True).first() if academy_slug else None
    response = (
        redirect('tenancy:academy_login', academy_slug=academy.slug)
        if academy
        else redirect('core:home')
    )
    response['Cache-Control'] = 'private, no-store, no-cache, must-revalidate, max-age=0'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response

@require_POST
def secure_logout(request):
    """Cierra sesión y evita restaurar datos privados desde caché/almacenamiento."""
    system_area = request.path.startswith('/sistema/') or bool(getattr(request.user, 'is_superuser', False))
    logout(request)
    target = '/sistema/ingresar/' if system_area else '/'
    response = redirect(target)
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response['Pragma'] = 'no-cache'
    response['Clear-Site-Data'] = '"cache", "storage"'
    return response


def global_access_disabled(request):
    return render(request, 'accounts/global_access_disabled.html', status=404)


class AcademyLoginView(auth_views.LoginView):
    template_name = 'accounts/login.html'
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = False

    def dispatch(self, request, *args, **kwargs):
        self.login_academy = get_object_or_404(
            Academy.objects.select_related('license'), slug=kwargs.get('academy_slug'), is_active=True,
        )
        request.academy = self.login_academy
        request.is_academy_public = True
        if not self.login_academy.access_enabled:
            return render(request, 'tenancy/license_blocked.html', {'academy': self.login_academy, 'public_view': True}, status=403)
        request.session['academy_slug'] = self.login_academy.slug
        if request.user.is_authenticated and not request.user.is_superuser:
            membership = membership_for_user(request.user, academy=self.login_academy)
            if membership and membership.status == AcademyMembership.Status.ACTIVE:
                request.academy_membership = membership
                request.academy_role = membership.role
                return redirect(role_home_url(request.user, self.login_academy))
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.get_user()
        if user.is_superuser:
            form.add_error(None, 'La cuenta maestra debe ingresar por Control del sistema.')
            return self.form_invalid(form)
        membership = membership_for_user(user, academy=self.login_academy)
        if not membership:
            form.add_error(None, 'Esta cuenta no pertenece a esta academia. Puedes solicitar acceso desde Crear cuenta.')
            return self.form_invalid(form)
        if membership.status == AcademyMembership.Status.PENDING:
            # Compatibilidad con registros creados por versiones anteriores.
            # Los estudiantes ya no requieren aprobación para pertenecer a la academia.
            if membership.role == AcademyMembership.Role.STUDENT and academy_has_available_seat(
                self.login_academy, AcademyMembership.Role.STUDENT, exclude_membership=membership
            ):
                membership.status = AcademyMembership.Status.ACTIVE
                membership.approved_at = timezone.now()
                membership.save(update_fields=['status', 'approved_at'])
            else:
                form.add_error(None, 'Tu cuenta todavía no está habilitada en esta academia. Contacta a su administración.')
                return self.form_invalid(form)
        if membership.status == AcademyMembership.Status.REJECTED:
            form.add_error(None, 'Tu solicitud fue rechazada por esta academia.')
            return self.form_invalid(form)
        if membership.status == AcademyMembership.Status.BLOCKED:
            form.add_error(None, 'Tu acceso a esta academia está bloqueado. Contacta a su administración.')
            return self.form_invalid(form)
        # IMPORTANTE: LoginView.form_valid() llama a django.contrib.auth.login().
        # Si en este navegador había otra cuenta autenticada (por ejemplo el
        # propietario global del sistema), Django hace session.flush() al cambiar
        # de usuario. Por eso academy_slug NO debe quedar guardado únicamente antes
        # del login: se perdería y /admin/ interpretaría falsamente que la academia
        # no tiene licencia/contexto.
        self.request.academy = self.login_academy
        self.request.academy_membership = membership
        self.request.academy_role = membership.role
        response = super().form_valid(form)
        # Restauramos el tenant DESPUÉS de que Django haya rotado/limpiado la sesión.
        self.request.session['academy_slug'] = self.login_academy.slug
        self.request.session.modified = True
        self.request.academy = self.login_academy
        self.request.academy_membership = membership
        self.request.academy_role = membership.role
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['academy'] = self.login_academy
        return context

    def get_success_url(self):
        requested = self.get_redirect_url()
        return requested or role_home_url(self.request.user, self.login_academy)


def _safe_registration_next(request):
    candidate = (request.POST.get('next') or request.GET.get('next') or '').strip()
    if not candidate:
        return ''
    if not url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return ''
    return candidate


def _registration_course(request, academy):
    course_slug = (request.POST.get('curso') or request.GET.get('curso') or '').strip()
    if not course_slug:
        return None
    # Import local para mantener accounts desacoplado del catálogo durante el arranque.
    from catalog.models import Course

    return (
        scope_courses(
            Course.objects.filter(
                slug=course_slug,
                status__in=[Course.Status.APPROVED, Course.Status.PUBLISHED],
            ).select_related('category'),
            academy,
        )
        .first()
    )


def _registration_destination(request, academy, selected_course):
    # Cuando el registro nació desde un curso, el destino queda fijado al checkout
    # de ese mismo curso. Así no se puede perder la selección entre GET y POST.
    if selected_course:
        return reverse('billing:checkout', args=[selected_course.slug])
    return _safe_registration_next(request)


def register(request, academy_slug=None):
    academy = get_object_or_404(Academy.objects.select_related('license'), slug=academy_slug, is_active=True)
    request.academy = academy
    request.is_academy_public = True
    request.session['academy_slug'] = academy.slug
    if not academy.access_enabled:
        return render(request, 'tenancy/license_blocked.html', {'academy': academy, 'public_view': True}, status=403)

    selected_course = _registration_course(request, academy)
    next_url = _registration_destination(request, academy, selected_course)
    flow_context = {
        'academy': academy,
        'selected_academy': academy,
        'selected_course': selected_course,
        'registration_next': next_url,
    }

    if request.user.is_authenticated and not request.user.is_superuser:
        existing_membership = membership_for_user(request.user, academy=academy)
        if existing_membership:
            if existing_membership.status == AcademyMembership.Status.ACTIVE:
                return redirect(next_url or role_home_url(request.user, academy))
            if existing_membership.status == AcademyMembership.Status.BLOCKED:
                messages.error(request, 'Tu cuenta está suspendida en esta academia.')
                return redirect('tenancy:academy_login', academy_slug=academy.slug)
            if existing_membership.status == AcademyMembership.Status.REJECTED:
                messages.error(request, 'Tu cuenta no está habilitada en esta academia.')
                return redirect('tenancy:academy_login', academy_slug=academy.slug)
        if request.method == 'POST':
            if not academy_has_available_seat(academy, AcademyMembership.Role.STUDENT):
                messages.error(request, 'Esta academia alcanzó el máximo de estudiantes permitido por su licencia.')
                return redirect('tenancy:academy_public', slug=academy.slug)
            bind_user(request.user, academy, role=AcademyMembership.Role.STUDENT, status=AcademyMembership.Status.ACTIVE)
            try:
                send_new_registration_notice(request, request.user, academy)
            except Exception as exc:
                logger.warning('No se pudo notificar al dueño sobre el nuevo registro en %s: %s', academy.slug, exc, exc_info=True)
            if not request.user.email_verified:
                try:
                    send_verification_email(request, request.user, academy)
                    messages.success(request, 'Ya perteneces a esta academia. Te enviamos un correo para verificar tu dirección.')
                except Exception:
                    messages.warning(request, 'Ya perteneces a esta academia. No pudimos enviar la verificación; podrás solicitarla otra vez desde tu panel.')
            else:
                messages.success(request, 'Ya perteneces a esta academia.')
            return redirect(next_url or role_home_url(request.user, academy))
        return render(request, 'accounts/join_academy.html', flow_context)

    form = RegisterForm(request.POST or None, academy=academy)
    if request.method == 'POST' and form.is_valid():
        if not academy_has_available_seat(academy, AcademyMembership.Role.STUDENT):
            messages.error(request, 'Esta academia alcanzó el máximo de estudiantes permitido por su licencia.')
            return render(request, 'accounts/register.html', {**flow_context, 'form': form})
        user, created = form.save()
        bind_user(user, academy, role=AcademyMembership.Role.STUDENT, status=AcademyMembership.Status.ACTIVE)
        try:
            send_new_registration_notice(request, user, academy)
        except Exception as exc:
            logger.warning('No se pudo notificar al dueño sobre el nuevo registro en %s: %s', academy.slug, exc, exc_info=True)
        if not user.email_verified:
            try:
                send_verification_email(request, user, academy)
                messages.success(request, 'Cuenta creada. Ya puedes continuar con el curso seleccionado; revisa tu correo para verificar tu dirección.')
            except Exception:
                messages.warning(request, 'Cuenta creada. Puedes continuar; la verificación no pudo enviarse y podrás solicitarla otra vez desde tu panel.')
        else:
            messages.success(request, 'Cuenta vinculada correctamente a esta academia.')
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        request.session['academy_slug'] = academy.slug
        return redirect(next_url or role_home_url(user, academy))
    return render(request, 'accounts/register.html', {**flow_context, 'form': form})


def verification_pending(request):
    slug = (request.session.get('academy_slug') or '').strip()
    if slug:
        return redirect('tenancy:membership_pending', slug=slug)
    return global_access_disabled(request)


def resend_verification(request):
    if not request.user.is_authenticated:
        return global_access_disabled(request)
    slug = (request.session.get('academy_slug') or '').strip()
    academy = Academy.objects.filter(slug=slug).first()
    if not academy:
        return global_access_disabled(request)
    next_url = (request.POST.get('next') or request.META.get('HTTP_REFERER') or '').strip()
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        next_url = role_home_url(request.user, academy)
    if request.user.email_verified:
        messages.info(request, 'Tu correo ya está verificado.')
        return redirect(next_url)
    if request.method == 'POST':
        try:
            send_verification_email(request, request.user, academy)
            messages.success(request, f'Enviamos un nuevo correo de verificación a {request.user.email}.')
        except Exception as exc:
            messages.error(request, f'No se pudo enviar la verificación en este momento. Detalle: {exc}')
    return redirect(next_url)


def verify_email(request, academy_slug, token):
    academy = get_object_or_404(Academy, slug=academy_slug)
    try:
        data = signing.loads(token, salt=SALT, max_age=60 * 60 * 24)
    except signing.BadSignature:
        messages.error(request, 'El enlace de verificación es inválido o venció.')
        return redirect('tenancy:membership_pending', slug=academy.slug)
    if data.get('academy') != academy.slug:
        messages.error(request, 'El enlace no pertenece a esta academia.')
        return redirect('tenancy:academy_public', slug=academy.slug)
    user = get_object_or_404(User, pk=data['uid'], email=data['email'])
    if not membership_for_user(user, academy=academy):
        messages.error(request, 'No existe una solicitud para esta academia.')
        return redirect('tenancy:academy_public', slug=academy.slug)
    if not user.email_verified:
        user.email_verified = True
        user.save(update_fields=['email_verified'])
    request.session['academy_slug'] = academy.slug
    messages.success(request, 'Correo verificado correctamente.')
    if request.user.is_authenticated and request.user.pk == user.pk:
        return redirect(role_home_url(user, academy))
    return redirect('tenancy:academy_login', academy_slug=academy.slug)


class AcademyPasswordResetView(auth_views.PasswordResetView):
    template_name = 'registration/password_reset_form.html'
    email_template_name = 'registration/password_reset_email.txt'
    html_email_template_name = 'registration/password_reset_email.html'
    subject_template_name = 'registration/password_reset_subject.txt'
    form_class = AcademyPasswordResetForm

    def dispatch(self, request, *args, **kwargs):
        self.academy = get_object_or_404(Academy.objects.select_related('license'), slug=kwargs.get('academy_slug'), is_active=True)
        request.academy = self.academy
        request.is_academy_public = True
        request.session['academy_slug'] = self.academy.slug
        if not self.academy.access_enabled:
            return render(request, 'tenancy/license_blocked.html', {'academy': self.academy, 'public_view': True}, status=403)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['academy'] = self.academy
        return kwargs

    def form_valid(self, form):
        if not academy_mail_available(self.academy):
            messages.error(self.request, 'El servicio de correo no está disponible temporalmente. Intenta nuevamente más tarde.')
            return self.form_invalid(form)
        try:
            opts = {
                'use_https': self.request.is_secure(),
                'token_generator': self.token_generator,
                'from_email': academy_sender(self.academy),
                'email_template_name': self.email_template_name,
                'subject_template_name': self.subject_template_name,
                'request': self.request,
                'html_email_template_name': self.html_email_template_name,
                'extra_email_context': {'academy': self.academy, 'academy_slug': self.academy.slug},
            }
            form.save(**opts)
        except Exception:
            messages.error(self.request, 'No se pudo enviar el correo en este momento. Intenta nuevamente o contacta al soporte de la academia.')
            return self.form_invalid(form)
        return redirect('tenancy:academy_password_reset_done', academy_slug=self.academy.slug)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['academy'] = self.academy
        return context


class AcademyPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = 'registration/password_reset_confirm.html'

    def dispatch(self, request, *args, **kwargs):
        self.academy = get_object_or_404(Academy, slug=kwargs.get('academy_slug'))
        request.academy = self.academy
        request.is_academy_public = True
        request.session['academy_slug'] = self.academy.slug
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse('tenancy:academy_password_reset_complete', args=[self.academy.slug])


def password_reset_done(request, academy_slug):
    academy = get_object_or_404(Academy, slug=academy_slug)
    request.academy = academy
    request.is_academy_public = True
    return render(request, 'registration/password_reset_done.html', {'academy': academy})


def password_reset_complete(request, academy_slug):
    academy = get_object_or_404(Academy, slug=academy_slug)
    request.academy = academy
    request.is_academy_public = True
    return render(request, 'registration/password_reset_complete.html', {'academy': academy})
