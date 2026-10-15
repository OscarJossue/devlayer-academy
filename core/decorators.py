from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def verified_email_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.email_verified:
            messages.warning(request, 'Verifica tu correo antes de continuar.')
            return redirect('accounts:verification_pending')
        return view_func(request, *args, **kwargs)
    return wrapped


def professor_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not (request.user.is_superuser or request.user.role in {'PROFESSOR', 'ADMIN', 'SUPERADMIN'}):
            messages.error(request, 'No tienes permiso para acceder a esta sección.')
            return redirect('learning:dashboard')
        if not request.user.is_superuser and not request.user.email_verified:
            messages.warning(request, 'Verifica tu correo antes de utilizar el panel del profesor.')
            return redirect('accounts:verification_pending')
        return view_func(request, *args, **kwargs)
    return wrapped


def superadmin_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not (request.user.is_superuser or request.user.role == 'SUPERADMIN'):
            messages.error(request, 'Esta sección es exclusiva del superadministrador.')
            if request.user.role in {'PROFESSOR', 'ADMIN'}:
                return redirect('catalog:professor_dashboard')
            return redirect('learning:dashboard')
        return view_func(request, *args, **kwargs)
    return wrapped
