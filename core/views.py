from django.shortcuts import render
from catalog.models import Course


def home(request):
    courses = Course.objects.filter(status=Course.Status.PUBLISHED).select_related('category').prefetch_related('instructor_links__user')[:9]
    return render(request, 'home.html', {'courses': courses})


def health(request):
    from django.http import JsonResponse
    return JsonResponse({'status': 'ok', 'service': 'devlayer-academy'})
