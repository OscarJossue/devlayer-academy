class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault('Permissions-Policy', 'camera=(self), microphone=(), geolocation=()')
        response.setdefault('Cross-Origin-Opener-Policy', 'same-origin')
        response.setdefault('X-Permitted-Cross-Domain-Policies', 'none')
        return response
