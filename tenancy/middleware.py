from django.shortcuts import redirect

from .models import AcademyMembership
from .services import academy_for_user, current_academy_from_session, membership_for_user, resolve_public_academy


class AcademyContextMiddleware:
    EXEMPT_PREFIXES = (
        '/static/', '/media/', '/health/', '/sistema/', '/academy/', '/cuenta/salir/',
        '/cuenta/recuperar/', '/cuenta/verificar/', '/cuenta/verificacion/',
        '/licencia-bloqueada/', '/certificados/verificar/',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.academy = None
        request.academy_membership = None
        request.academy_role = ''
        request.is_academy_public = request.path.startswith('/academy/')

        public_academy = resolve_public_academy(request) if request.is_academy_public else None
        user = getattr(request, 'user', None)

        if public_academy:
            request.academy = public_academy
            request.session['academy_slug'] = public_academy.slug

        if user and user.is_authenticated and not user.is_superuser:
            academy = request.academy or current_academy_from_session(request)

            # Recuperación defensiva de contexto. Si la sesión perdió academy_slug
            # durante un cambio de usuario, solo inferimos la academia cuando el
            # usuario pertenece a UNA única academia. Nunca adivinamos entre varias.
            if not academy:
                academy = academy_for_user(user)
                if academy:
                    request.session['academy_slug'] = academy.slug
                    request.session.modified = True

            if academy:
                membership = membership_for_user(user, academy=academy)
                request.academy = academy
                request.academy_membership = membership
                request.academy_role = membership.role if membership else ''

            if not any(request.path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES):
                # Ausencia de contexto NO significa licencia bloqueada. Antes se
                # mezclaban ambos casos y se mostraba una pantalla falsa de licencia.
                if not request.academy:
                    if request.path == '/':
                        return self.get_response(request)
                    return redirect('core:home')
                if not request.academy.access_enabled:
                    # Conservamos el slug para que la pantalla de bloqueo pueda
                    # mostrar la academia y la razón real del bloqueo.
                    request.session['academy_slug'] = request.academy.slug
                    request.session.modified = True
                    return redirect('tenancy:license_blocked')
                if not request.academy_membership or request.academy_membership.status != AcademyMembership.Status.ACTIVE:
                    return redirect('tenancy:membership_pending', slug=request.academy.slug)

        return self.get_response(request)
