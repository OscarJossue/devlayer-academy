from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from tenancy.models import AcademyMembership
from tenancy.services import current_academy_from_session, membership_for_user


def _academy_context(request):
    academy = getattr(request, 'academy', None) or current_academy_from_session(request)
    if not academy:
        return None, None
    membership = membership_for_user(request.user, academy=academy)
    if membership:
        request.academy = academy
        request.academy_membership = membership
        request.academy_role = membership.role
    return academy, membership


def _redirect_to_academy_login(request, academy=None):
    academy = academy or getattr(request, 'academy', None) or current_academy_from_session(request)
    if academy:
        return redirect('tenancy:academy_login', academy_slug=academy.slug)
    return redirect('core:home')


def verified_email_required(view_func):
    """Compatibilidad histórica: exige membresía activa, no correo verificado.

    La verificación de correo es ahora una recomendación visible dentro de la
    academia, pero no bloquea el catálogo, pagos ni contenido que el estudiante
    ya tenga habilitado. El control real del contenido sigue siendo la matrícula.
    """
    @login_required(login_url='/')
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if request.user.is_superuser:
            return redirect('tenancy:system_dashboard')
        academy, membership = _academy_context(request)
        if not academy:
            messages.error(request, 'Accede desde el enlace de tu academia.')
            return redirect('core:home')
        if not academy.access_enabled:
            return redirect('tenancy:license_blocked')
        if not membership or membership.status != AcademyMembership.Status.ACTIVE:
            return redirect('tenancy:membership_pending', slug=academy.slug)
        return view_func(request, *args, **kwargs)
    return wrapped


def professor_required(view_func):
    @login_required(login_url='/')
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if request.user.is_superuser:
            return redirect('tenancy:system_dashboard')
        academy, membership = _academy_context(request)
        if not academy:
            return _redirect_to_academy_login(request)
        if not academy.access_enabled:
            return redirect('tenancy:license_blocked')
        if not membership or membership.status != AcademyMembership.Status.ACTIVE:
            return redirect('tenancy:membership_pending', slug=academy.slug)
        if membership.role not in {
            AcademyMembership.Role.PROFESSOR,
            AcademyMembership.Role.ADMIN,
            AcademyMembership.Role.OWNER,
        }:
            messages.error(request, 'No tienes permiso para acceder a esta sección.')
            return redirect('learning:dashboard')
        return view_func(request, *args, **kwargs)
    return wrapped


def superadmin_required(view_func):
    @login_required(login_url='/')
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if request.user.is_superuser:
            return redirect('tenancy:system_dashboard')
        academy, membership = _academy_context(request)
        if not academy:
            return _redirect_to_academy_login(request)
        if not academy.access_enabled:
            return redirect('tenancy:license_blocked')
        if not membership or membership.status != AcademyMembership.Status.ACTIVE:
            return redirect('tenancy:membership_pending', slug=academy.slug)
        if membership.role != AcademyMembership.Role.OWNER:
            messages.error(request, 'Esta sección es exclusiva del dueño de la academia.')
            if membership.role in {AcademyMembership.Role.PROFESSOR, AcademyMembership.Role.ADMIN}:
                return redirect('catalog:professor_dashboard')
            return redirect('learning:dashboard')
        return view_func(request, *args, **kwargs)
    return wrapped


def platform_owner_required(view_func):
    @login_required(login_url='/sistema/ingresar/')
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, 'Acceso exclusivo del propietario del sistema.')
            return redirect('core:home')
        return view_func(request, *args, **kwargs)
    return wrapped
