from urllib.parse import quote

from django.conf import settings


def _digits(value):
    return ''.join(ch for ch in (value or '') if ch.isdigit())


def _whatsapp_url(number, message):
    number = _digits(number)
    if not number:
        return ''
    return f'https://wa.me/{number}?text={quote(message)}'


def global_settings(request):
    context = {
        'SITE_NAME': settings.SITE_NAME,
        'academy_has_certificate_courses': False,
        'student_certificate_module_visible': False,
        'academy_support_title': '',
        'academy_support_contacts': [],
        'owner_support_whatsapp_url': '',
        'professor_can_manage_student_payments': False,
        'owner_action_counts': {'total': 0, 'pending_payments': 0, 'pending_memberships': 0, 'review_courses': 0},
    }
    user = getattr(request, 'user', None)
    academy = getattr(request, 'academy', None)
    if not user or not getattr(user, 'is_authenticated', False) or getattr(user, 'is_superuser', False) or not academy:
        return context

    role = getattr(request, 'academy_role', '')

    # El dueño de la academia sí puede contactar a DevLayer Studio. Este número
    # jamás se reutiliza para estudiantes ni profesores.
    if role == 'OWNER':
        platform_number = _digits(getattr(settings, 'WHATSAPP_NUMBER', ''))
        if platform_number:
            context['owner_support_whatsapp_url'] = _whatsapp_url(
                platform_number,
                f'Hola DevLayer Studio, necesito soporte para {academy.name}. Mi usuario es {user.email}.',
            )
        try:
            from billing.models import Payment
            from catalog.models import Course
            from tenancy.models import AcademyMembership
            from tenancy.services import scope_courses

            course_ids = scope_courses(Course.objects.all(), academy).values_list('pk', flat=True)
            pending_payments = Payment.objects.filter(
                order__course_id__in=course_ids,
                status=Payment.Status.PENDING,
            ).count()
            pending_memberships = AcademyMembership.objects.filter(
                academy=academy,
                status=AcademyMembership.Status.PENDING,
                role__in=[AcademyMembership.Role.OWNER, AcademyMembership.Role.PROFESSOR, AcademyMembership.Role.ADMIN],
            ).count()
            review_courses = Course.objects.filter(
                pk__in=course_ids,
                status=Course.Status.REVIEW,
            ).count()
            context['owner_action_counts'] = {
                'pending_payments': pending_payments,
                'pending_memberships': pending_memberships,
                'review_courses': review_courses,
                'total': pending_payments + pending_memberships + review_courses,
            }
        except Exception:
            pass
    else:
        # Estudiantes y profesores solo ven contactos configurados por SU academia.
        context['academy_support_title'] = (academy.support_title or 'Soporte de la academia').strip()
        contacts = []
        for index, (label, number) in enumerate((
            (academy.support_whatsapp_1_label, academy.support_whatsapp_1_number),
            (academy.support_whatsapp_2_label, academy.support_whatsapp_2_number),
        ), start=1):
            number = _digits(number)
            if not number:
                continue
            label = (label or ('Soporte' if index == 1 else 'Atención')).strip()
            contacts.append({
                'label': label,
                'number': number,
                'url': _whatsapp_url(
                    number,
                    f'Hola, necesito ayuda en {academy.name}. Mi usuario es {user.email}.',
                ),
            })
        context['academy_support_contacts'] = contacts

    membership = getattr(request, 'academy_membership', None)
    if membership:
        context['professor_can_manage_student_payments'] = bool(
            getattr(membership, 'can_manage_student_payments', False)
            or role == 'OWNER'
        )

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
