from django.shortcuts import redirect, render


def home(request):
    # No existe catálogo/login global. Los usuarios de academia siempre deben
    # entrar por /academy/<slug>/. Si ya existe contexto de academia activo,
    # enviamos al inicio correspondiente sin intentar adivinar otra academia.
    if request.user.is_authenticated:
        if request.user.is_superuser:
            return redirect('tenancy:system_dashboard')
        membership = getattr(request, 'academy_membership', None)
        academy = getattr(request, 'academy', None)
        if academy and membership and membership.status == 'ACTIVE':
            from accounts.views import role_home_url
            return redirect(role_home_url(request.user, academy))
    return render(request, 'home.html')


def health(request):
    from django.http import JsonResponse
    return JsonResponse({'status': 'ok', 'service': 'devlayer-academy'})
