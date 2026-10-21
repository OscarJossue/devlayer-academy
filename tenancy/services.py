from django.db.models import QuerySet

from .models import (
    Academy, AcademyBankAccount, AcademyCategory, AcademyCourse,
    AcademyMembership, PlatformAuditLog,
)


def membership_for_user(user, academy=None, slug=None, statuses=None):
    if not getattr(user, 'is_authenticated', False) or getattr(user, 'is_superuser', False):
        return None
    qs = AcademyMembership.objects.select_related('academy', 'academy__license').filter(user_id=user.pk)
    if academy is not None:
        qs = qs.filter(academy=academy)
    elif slug:
        qs = qs.filter(academy__slug=slug)
    if statuses:
        qs = qs.filter(status__in=statuses)
    return qs.first()


def membership_for_request(request, require_active=False):
    user = getattr(request, 'user', None)
    if not user or not getattr(user, 'is_authenticated', False) or getattr(user, 'is_superuser', False):
        return None
    academy = getattr(request, 'academy', None)
    if not academy:
        slug = (request.session.get('academy_slug') or '').strip()
        if slug:
            academy = Academy.objects.select_related('license').filter(slug=slug).first()
    if not academy:
        return None
    statuses = [AcademyMembership.Status.ACTIVE] if require_active else None
    return membership_for_user(user, academy=academy, statuses=statuses)


def academy_for_user(user, academy=None, slug=None):
    membership = membership_for_user(user, academy=academy, slug=slug)
    if membership:
        return membership.academy
    if academy is not None or slug:
        return None
    # Compatibilidad segura: solo resolvemos automáticamente si existe una única membresía.
    if not getattr(user, 'is_authenticated', False) or getattr(user, 'is_superuser', False):
        return None
    memberships = list(
        AcademyMembership.objects.select_related('academy', 'academy__license').filter(user_id=user.pk)[:2]
    )
    return memberships[0].academy if len(memberships) == 1 else None


def bind_user(user, academy, role=AcademyMembership.Role.STUDENT, status=AcademyMembership.Status.ACTIVE, approved_by=None):
    defaults = {'role': role, 'status': status}
    if status == AcademyMembership.Status.ACTIVE:
        from django.utils import timezone
        defaults['approved_at'] = timezone.now()
        defaults['approved_by_id'] = getattr(approved_by, 'pk', None)
    membership, _ = AcademyMembership.objects.update_or_create(
        academy=academy,
        user_id=user.pk,
        defaults=defaults,
    )
    return membership


def bind_course(course, academy):
    return AcademyCourse.objects.update_or_create(course_id=course.pk, defaults={'academy': academy})[0]


def bind_category(category, academy):
    return AcademyCategory.objects.update_or_create(category_id=category.pk, defaults={'academy': academy})[0]


def bind_bank(bank, academy):
    return AcademyBankAccount.objects.update_or_create(bank_account_id=bank.pk, defaults={'academy': academy})[0]


def academy_memberships(academy, roles=None, statuses=None):
    qs = AcademyMembership.objects.filter(academy=academy)
    if roles:
        qs = qs.filter(role__in=roles)
    if statuses:
        qs = qs.filter(status__in=statuses)
    return qs


def academy_user_ids(academy, roles=None, statuses=None):
    return academy_memberships(academy, roles=roles, statuses=statuses).values_list('user_id', flat=True)


def academy_course_ids(academy):
    return AcademyCourse.objects.filter(academy=academy).values_list('course_id', flat=True)


def academy_category_ids(academy):
    return AcademyCategory.objects.filter(academy=academy).values_list('category_id', flat=True)


def academy_bank_ids(academy):
    return AcademyBankAccount.objects.filter(academy=academy).values_list('bank_account_id', flat=True)


def scope_users(qs: QuerySet, academy, roles=None, statuses=None):
    return qs.filter(pk__in=academy_user_ids(academy, roles=roles, statuses=statuses), is_superuser=False)


def scope_courses(qs: QuerySet, academy):
    return qs.filter(pk__in=academy_course_ids(academy))


def scope_categories(qs: QuerySet, academy):
    return qs.filter(pk__in=academy_category_ids(academy))


def scope_banks(qs: QuerySet, academy):
    return qs.filter(pk__in=academy_bank_ids(academy))


def academy_for_course(course):
    binding = AcademyCourse.objects.select_related('academy', 'academy__license').filter(course_id=course.pk).first()
    return binding.academy if binding else None


def academy_for_category(category):
    binding = AcademyCategory.objects.select_related('academy').filter(category_id=category.pk).first()
    return binding.academy if binding else None


def academy_for_bank(bank):
    binding = AcademyBankAccount.objects.select_related('academy').filter(bank_account_id=bank.pk).first()
    return binding.academy if binding else None


def academy_has_available_seat(academy, role=AcademyMembership.Role.STUDENT, exclude_membership=None):
    """Valida cupos activos por rol según la licencia de la academia."""
    license_obj = academy.current_license
    if not license_obj or not license_obj.is_valid:
        return False
    limit = license_obj.role_limit(role)
    if not limit:
        return True
    qs = AcademyMembership.objects.filter(
        academy=academy,
        role=role,
        status=AcademyMembership.Status.ACTIVE,
    )
    if exclude_membership is not None:
        qs = qs.exclude(pk=exclude_membership.pk)
    return qs.count() < limit


def academy_license_usage(academy):
    license_obj = academy.current_license
    if not license_obj:
        return {}
    def row(role, limit):
        used = AcademyMembership.objects.filter(
            academy=academy, role=role, status=AcademyMembership.Status.ACTIVE,
        ).count()
        pct = 0 if not limit else min(100, round((used / limit) * 100))
        return {'used': used, 'limit': limit, 'percent': pct, 'unlimited': not bool(limit)}
    return {
        'students': row(AcademyMembership.Role.STUDENT, license_obj.max_users),
        'professors': row(AcademyMembership.Role.PROFESSOR, license_obj.max_professors),
        'admins': row(AcademyMembership.Role.ADMIN, license_obj.max_admins),
        'owners': row(AcademyMembership.Role.OWNER, 1),
    }


def active_academies():
    return [
        academy
        for academy in Academy.objects.filter(is_active=True).select_related('license')
        if academy.access_enabled
    ]


def _slug_from_path(request):
    parts = [part for part in request.path_info.split('/') if part]
    return parts[1].strip() if len(parts) >= 2 and parts[0] == 'academy' else ''


def resolve_public_academy(request):
    # Si el middleware ya resolvió una academia (ruta pública por slug o sesión
    # autenticada), esa es la única academia válida para la petición.
    academy = getattr(request, 'academy', None)
    if academy:
        return academy

    slug = _slug_from_path(request)
    if slug:
        academy = Academy.objects.select_related('license').filter(slug=slug, is_active=True).first()
        if academy and academy.access_enabled:
            return academy

    host = request.get_host().split(':')[0].lower()
    if host not in {'localhost', '127.0.0.1'}:
        academy = Academy.objects.select_related('license').filter(custom_domain=host, is_active=True).first()
        if academy and academy.access_enabled:
            return academy
    return None


def current_academy_from_session(request):
    slug = (request.session.get('academy_slug') or '').strip()
    if not slug:
        return None
    return Academy.objects.select_related('license').filter(slug=slug).first()


def academy_login_path(academy):
    return f'/academy/{academy.slug}/ingresar/' if academy else '/'


def log_platform_event(actor, action, academy=None, metadata=None):
    return PlatformAuditLog.objects.create(
        actor_email=getattr(actor, 'email', '') or '',
        academy=academy,
        action=action,
        metadata=metadata or {},
    )
