from django.conf import settings


def global_settings(request):
    context = {
        'SITE_NAME': settings.SITE_NAME,
        'academy_has_certificate_courses': False,
        'student_certificate_module_visible': False,
    }
    user = getattr(request, 'user', None)
    academy = getattr(request, 'academy', None)
    if not user or not getattr(user, 'is_authenticated', False) or getattr(user, 'is_superuser', False) or not academy:
        return context

    try:
        from catalog.models import Course
        from certificates.models import Certificate
        from tenancy.services import scope_courses

        course_ids = scope_courses(Course.objects.all(), academy).values_list('pk', flat=True)
        issued_any = Certificate.objects.filter(enrollment__course_id__in=course_ids).exists()
        context['academy_has_certificate_courses'] = (
            Course.objects.filter(pk__in=course_ids, certificate_enabled=True).exists() or issued_any
        )
        context['student_certificate_module_visible'] = (
            Certificate.objects.filter(
                enrollment__user=user,
                enrollment__course_id__in=course_ids,
            ).exists()
            or user.enrollments.filter(
                course_id__in=course_ids,
                course__certificate_enabled=True,
            ).exists()
        )
    except Exception:
        # El contexto visual nunca debe impedir que una página cargue.
        pass
    return context
