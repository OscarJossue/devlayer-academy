from django.conf import settings


class LocalDevelopmentOriginMiddleware:
    """Corrige únicamente en desarrollo local un Origin opaco enviado por el navegador.

    Algunos contextos de navegador pueden enviar ``Origin: null`` incluso cuando el
    usuario está trabajando en localhost. Django lo rechaza correctamente por CSRF.
    Esta compatibilidad se limita estrictamente a DEBUG + hosts locales y nunca se
    activa en producción ni para dominios externos.
    """

    LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1'}
    UNSAFE_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.DEBUG and request.method in self.UNSAFE_METHODS:
            origin = (request.META.get('HTTP_ORIGIN') or '').strip().lower()
            raw_host = request.get_host()
            host = raw_host.split(':', 1)[0].strip('[]').lower()
            if origin == 'null' and host in self.LOCAL_HOSTS:
                scheme = 'https' if request.is_secure() else 'http'
                request.META['HTTP_ORIGIN'] = f'{scheme}://{raw_host}'
        return self.get_response(request)


class SecurityHeadersMiddleware:
    """Cabeceras defensivas para paneles autenticados y contenido protegido.

    La aplicación usa algunos scripts/estilos inline heredados, por eso la CSP
    conserva ``unsafe-inline`` hasta que todo el frontend pueda migrarse a nonces.
    Aun así bloquea plugins, iframes de terceros no autorizados y captura iniciada
    desde el propio sitio mediante Screen Capture API.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        path = request.path or ''
        is_secure_video_frame = '/video-seguro/' in path

        response.setdefault(
            'Permissions-Policy',
            'camera=(self), microphone=(), geolocation=(), display-capture=(), '
            'payment=(), usb=(), serial=(), bluetooth=()'
        )
        response.setdefault('Cross-Origin-Opener-Policy', 'same-origin')
        response.setdefault('Cross-Origin-Resource-Policy', 'same-origin')
        response.setdefault('X-Permitted-Cross-Domain-Policies', 'none')
        response.setdefault('X-Download-Options', 'noopen')
        response.setdefault('Referrer-Policy', 'same-origin')

        frame_ancestors = "'self'" if is_secure_video_frame else "'none'"
        csp = (
            "default-src 'self'; "
            "base-uri 'self'; "
            "object-src 'none'; "
            f"frame-ancestors {frame_ancestors}; "
            "form-action 'self'; "
            "img-src 'self' data: blob:; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "script-src 'self' 'unsafe-inline' https://www.youtube.com https://www.youtube-nocookie.com; "
            "frame-src 'self' https://www.youtube-nocookie.com https://www.youtube.com; "
            "connect-src 'self' https://www.youtube.com https://www.youtube-nocookie.com; "
            "media-src 'self' blob:; "
            "worker-src 'self' blob:;"
        )
        response.setdefault('Content-Security-Policy', csp)

        # Las pantallas autenticadas nunca deben quedar reutilizables desde caché.
        # Esto evita que, después de cerrar sesión, el botón Atrás muestre una copia
        # visual del panel sin volver a validar la sesión en Django.
        user = getattr(request, 'user', None)
        is_private_panel = bool(
            user
            and getattr(user, 'is_authenticated', False)
            and not getattr(request, 'is_academy_public', False)
            and not path.startswith(('/static/', '/media/'))
        )
        is_auth_page = '/ingresar/' in path or path.startswith('/cuenta/salir/') or path.startswith('/sistema/salir/')
        is_private_media = '/material/pagina/' in path or is_secure_video_frame
        if is_private_panel or is_auth_page or is_private_media:
            response['Cache-Control'] = 'private, no-store, no-cache, must-revalidate, max-age=0'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
            response['X-Robots-Tag'] = 'noindex, nofollow, noarchive, nosnippet'
            vary = response.get('Vary', '')
            if 'Cookie' not in vary:
                response['Vary'] = f'{vary}, Cookie'.strip(', ')
        return response
