from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.db.models import Q, Sum
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.services import send_membership_approved_email, send_verification_email
from audit.models import AuditLog
from audit.services import log_event
from billing.models import BankAccount, Payment
from billing.services import approve_payment
from catalog.models import Category, Course, CourseInstructor
from certificates.models import Certificate
from certificates.design import preview_style_context
from certificates.rendering import render_certificate_pdf
from learning.models import Enrollment
from learning.services import progress_percentage
from tenancy.mail import send_academy_mail, platform_mail_available
from tenancy.models import AcademyMembership
from tenancy.services import (
    academy_has_available_seat, academy_license_usage, bind_bank, create_academy_category,
    scope_banks, scope_categories, scope_courses, scope_users,
)

from .decorators import superadmin_required
from .superadmin_forms import AcademyBrandingForm, AcademySupportSettingsForm, AcademyPaymentSettingsForm, AcademySMTPForm, AcademyCertificateStyleForm, BankAccountForm, CategoryForm, EnrollmentCreateForm, EnrollmentEditForm, SuperadminUserCreationForm


def _query(request):
    return (request.GET.get('q') or '').strip()


def _payments_for(academy):
    return Payment.objects.filter(order__course__pk__in=scope_courses(Course.objects.all(), academy).values_list('pk', flat=True))


def _enrollments_for(academy):
    return Enrollment.objects.filter(course__pk__in=scope_courses(Course.objects.all(), academy).values_list('pk', flat=True))


def _certificates_for(academy):
    return Certificate.objects.filter(enrollment__course__pk__in=scope_courses(Course.objects.all(), academy).values_list('pk', flat=True))


def _enrollment_progress_row(enrollment):
    progress = progress_percentage(enrollment)
    completed = bool(enrollment.status == Enrollment.Status.COMPLETED or enrollment.certified_at or progress >= 100)
    blocked = enrollment.status in {Enrollment.Status.BLOCKED, Enrollment.Status.REVOKED, Enrollment.Status.EXPIRED}
    if blocked:
        stage = 'blocked'
        stage_label = 'Bloqueado'
    elif completed:
        stage = 'completed'
        stage_label = 'Completado'
    elif progress > 0:
        stage = 'progress'
        stage_label = 'En proceso'
    else:
        stage = 'not_started'
        stage_label = 'Sin iniciar'
    return {
        'enrollment': enrollment,
        'progress': progress,
        'stage': stage,
        'stage_label': stage_label,
    }


def _course_academic_summary(course):
    enrollments = list(course.enrollments.select_related('user').all())
    rows = [_enrollment_progress_row(item) for item in enrollments]
    payments = Payment.objects.filter(order__course=course)
    return {
        'course': course,
        'rows': rows,
        'total': len(rows),
        'completed': sum(1 for row in rows if row['stage'] == 'completed'),
        'in_progress': sum(1 for row in rows if row['stage'] == 'progress'),
        'not_started': sum(1 for row in rows if row['stage'] == 'not_started'),
        'blocked': sum(1 for row in rows if row['stage'] == 'blocked'),
        'pending_payments': payments.filter(status=Payment.Status.PENDING).count(),
        'approved_payments': payments.filter(status=Payment.Status.APPROVED).count(),
    }


def _course_user_rows(course, academy, payments):
    """Usuarios realmente relacionados con un curso: equipo, matrículas o pagos."""
    enrollments = list(course.enrollments.select_related('user').all())
    enrollment_by_user = {item.user_id: item for item in enrollments}
    latest_payment_by_user = {}
    for payment in payments:
        latest_payment_by_user.setdefault(payment.order.user_id, payment)

    instructor_ids = list(course.instructor_links.values_list('user_id', flat=True))
    user_ids = set(instructor_ids) | set(enrollment_by_user) | set(latest_payment_by_user)
    memberships = {
        item.user_id: item
        for item in AcademyMembership.objects.filter(academy=academy, user_id__in=user_ids)
    }
    users = {item.pk: item for item in User.objects.filter(pk__in=user_ids)}
    rows = []
    for user_id in user_ids:
        user = users.get(user_id)
        if not user:
            continue
        membership = memberships.get(user_id)
        enrollment = enrollment_by_user.get(user_id)
        payment = latest_payment_by_user.get(user_id)
        if user_id in instructor_ids:
            relation = 'Profesor del curso'
        elif enrollment:
            relation = 'Estudiante con acceso'
        elif payment and payment.status == Payment.Status.PENDING:
            relation = 'Estudiante · pago pendiente'
        elif payment:
            relation = f'Estudiante · {payment.get_status_display().lower()}'
        else:
            relation = 'Usuario relacionado'
        rows.append({
            'user': user,
            'membership': membership,
            'relation': relation,
            'enrollment': enrollment,
            'payment': payment,
        })
    return sorted(rows, key=lambda row: (0 if 'Profesor' in row['relation'] else 1, row['user'].display_name.lower()))


@superadmin_required
def dashboard(request):
    academy = request.academy
    memberships = AcademyMembership.objects.filter(academy=academy)
    users_qs = scope_users(User.objects.all(), academy)
    courses_qs = scope_courses(Course.objects.all(), academy)
    payments_qs = _payments_for(academy)
    enrollments_qs = _enrollments_for(academy)
    certificates_qs = _certificates_for(academy)
    approved_revenue = payments_qs.filter(status=Payment.Status.APPROVED).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    recent_memberships = list(memberships.order_by('-created_at')[:6])
    recent_map = {str(u.pk): u for u in User.objects.filter(pk__in=[m.user_id for m in recent_memberships])}
    recent_users = [{'user': recent_map.get(str(m.user_id)), 'membership': m} for m in recent_memberships if recent_map.get(str(m.user_id))]
    academic_rows = [_enrollment_progress_row(item) for item in enrollments_qs.select_related('user', 'course')]
    context = {
        'academy': academy,
        'stats': {
            'students': memberships.filter(role=AcademyMembership.Role.STUDENT, status=AcademyMembership.Status.ACTIVE).count(),
            'unverified_students': User.objects.filter(
                pk__in=memberships.filter(
                    role=AcademyMembership.Role.STUDENT, status=AcademyMembership.Status.ACTIVE
                ).values_list('user_id', flat=True),
                email_verified=False,
            ).count(),
            'professors': memberships.filter(role=AcademyMembership.Role.PROFESSOR, status=AcademyMembership.Status.ACTIVE).count(),
            'admins': memberships.filter(role=AcademyMembership.Role.ADMIN, status=AcademyMembership.Status.ACTIVE).count(),
            'courses': courses_qs.count(),
            'pending_courses': courses_qs.filter(status__in=[Course.Status.REVIEW, Course.Status.APPROVED]).count(),
            'active_enrollments': enrollments_qs.filter(status=Enrollment.Status.ACTIVE).count(),
            'pending_payments': payments_qs.filter(status=Payment.Status.PENDING).count(),
            'certificates': certificates_qs.filter(status=Certificate.Status.VALID).count(),
            'revenue': approved_revenue,
            'completed_enrollments': sum(1 for row in academic_rows if row['stage'] == 'completed'),
            'in_progress_enrollments': sum(1 for row in academic_rows if row['stage'] == 'progress'),
            'not_started_enrollments': sum(1 for row in academic_rows if row['stage'] == 'not_started'),
            'blocked_enrollments': sum(1 for row in academic_rows if row['stage'] == 'blocked'),
        },
        'recent_courses': courses_qs.select_related('category', 'created_by').order_by('-updated_at')[:6],
        'recent_payments': payments_qs.select_related('order__user', 'order__course').order_by('-created_at')[:6],
        'recent_users': recent_users,
        'license_obj': academy.current_license,
        'license_usage': academy_license_usage(academy),
    }
    return render(request, 'superadmin/dashboard.html', context)


@superadmin_required
def users(request):
    memberships = AcademyMembership.objects.filter(
        academy=request.academy,
        role__in=[AcademyMembership.Role.OWNER, AcademyMembership.Role.PROFESSOR, AcademyMembership.Role.ADMIN],
    ).order_by('-created_at')
    q = _query(request); role = request.GET.get('rol') or ''; state = request.GET.get('estado') or ''
    if role:
        memberships = memberships.filter(role=role)
    if state:
        memberships = memberships.filter(status=state)
    if q:
        matching_ids = User.objects.filter(
            Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q),
            pk__in=memberships.values_list('user_id', flat=True),
        ).values_list('pk', flat=True)
        memberships = memberships.filter(user_id__in=matching_ids)
    membership_list = list(memberships[:250])
    user_map = {str(u.pk): u for u in User.objects.filter(pk__in=[m.user_id for m in membership_list])}
    rows = [{'user': user_map.get(str(m.user_id)), 'membership': m} for m in membership_list if user_map.get(str(m.user_id))]
    roles = [choice for choice in AcademyMembership.Role.choices if choice[0] in {AcademyMembership.Role.OWNER, AcademyMembership.Role.PROFESSOR, AcademyMembership.Role.ADMIN}]
    states = AcademyMembership.Status.choices
    all_memberships = AcademyMembership.objects.filter(academy=request.academy)
    staff_memberships = all_memberships.filter(role__in=[AcademyMembership.Role.OWNER, AcademyMembership.Role.PROFESSOR, AcademyMembership.Role.ADMIN])
    summary = {
        'pending': staff_memberships.filter(status=AcademyMembership.Status.PENDING).count(),
        'professors': staff_memberships.filter(role=AcademyMembership.Role.PROFESSOR, status=AcademyMembership.Status.ACTIVE).count(),
        'admins': staff_memberships.filter(role=AcademyMembership.Role.ADMIN, status=AcademyMembership.Status.ACTIVE).count(),
        'blocked': staff_memberships.filter(status=AcademyMembership.Status.BLOCKED).count(),
    }
    return render(request, 'superadmin/users.html', {
        'users_list': rows, 'roles': roles, 'states': states, 'q': q,
        'role_filter': role, 'state_filter': state, 'summary': summary,
    })


@superadmin_required
def student_courses(request):
    courses_qs = scope_courses(Course.objects.all(), request.academy).select_related('category').order_by('title')
    rows = []
    for course in courses_qs:
        enrollments = course.enrollments.select_related('user')
        pending_payments = Payment.objects.filter(order__course=course, status=Payment.Status.PENDING).count()
        rows.append({
            'course': course,
            'students': enrollments.values('user_id').distinct().count(),
            'active': enrollments.filter(status=Enrollment.Status.ACTIVE).count(),
            'completed': enrollments.filter(status=Enrollment.Status.COMPLETED).count(),
            'pending_payments': pending_payments,
        })
    return render(request, 'superadmin/student_courses.html', {'course_rows': rows})


@superadmin_required
def student_course_users(request, course_id):
    course = get_object_or_404(
        scope_courses(Course.objects.all(), request.academy).select_related('category'),
        pk=course_id,
    )
    payments = list(
        Payment.objects.filter(order__course=course)
        .select_related('order__user')
        .order_by('-created_at')
    )
    latest_payment = {}
    for payment in payments:
        latest_payment.setdefault(payment.order.user_id, payment)
    enrollments = list(course.enrollments.select_related('user').order_by('user__first_name', 'user__last_name', 'user__email'))
    enrollment_by_user = {item.user_id: item for item in enrollments}
    student_memberships = AcademyMembership.objects.filter(
        academy=request.academy, role=AcademyMembership.Role.STUDENT
    )
    membership_by_user = {item.user_id: item for item in student_memberships}
    user_ids = set(enrollment_by_user) | set(latest_payment)
    users_map = {item.pk: item for item in User.objects.filter(pk__in=user_ids)}
    rows = []
    for user_id in user_ids:
        user = users_map.get(user_id)
        if not user:
            continue
        enrollment = enrollment_by_user.get(user_id)
        payment = latest_payment.get(user_id)
        rows.append({
            'user': user,
            'membership': membership_by_user.get(user_id),
            'enrollment': enrollment,
            'payment': payment,
            'progress': progress_percentage(enrollment) if enrollment else 0,
        })
    rows.sort(key=lambda row: row['user'].display_name.lower())
    return render(request, 'superadmin/student_course_users.html', {
        'course': course,
        'student_rows': rows,
        'pending_payments': sum(1 for row in rows if row['payment'] and row['payment'].status == Payment.Status.PENDING),
    })


@superadmin_required
def user_detail(request, user_id):
    membership = get_object_or_404(AcademyMembership, academy=request.academy, user_id=user_id)
    user = get_object_or_404(User, pk=user_id, is_superuser=False)

    if request.method == 'POST' and request.POST.get('section') == 'professor_permissions':
        if membership.role not in {AcademyMembership.Role.PROFESSOR, AcademyMembership.Role.ADMIN}:
            messages.error(request, 'Este permiso solo puede asignarse a profesores o administradores docentes.')
            return redirect('superadmin:user_detail', user_id=user.id)
        membership.can_manage_student_payments = request.POST.get('can_manage_student_payments') == 'on'
        membership.save(update_fields=['can_manage_student_payments'])
        log_event(
            request.user,
            'permisos_profesor_actualizados',
            user,
            {'gestiona_estudiantes_pagos': membership.can_manage_student_payments},
            request,
        )
        if membership.can_manage_student_payments:
            messages.success(request, 'Permiso activado. El profesor podrá gestionar pagos y accesos únicamente en sus cursos asignados.')
        else:
            messages.success(request, 'Permiso retirado. El profesor conserva únicamente la gestión académica de sus cursos.')
        return redirect('superadmin:user_detail', user_id=user.id)

    enrollment_qs = _enrollments_for(request.academy).filter(user=user).select_related('course').order_by('-created_at')
    enrollment_rows = [_enrollment_progress_row(item) for item in enrollment_qs]
    professor_courses = scope_courses(Course.objects.all(), request.academy).filter(instructor_links__user=user).distinct().select_related('category')
    context = {
        'profile_user': user,
        'membership': membership,
        'enrollment_rows': enrollment_rows,
        'professor_courses': professor_courses,
        'student_stats': {
            'courses': len(enrollment_rows),
            'completed': sum(1 for row in enrollment_rows if row['stage'] == 'completed'),
            'in_progress': sum(1 for row in enrollment_rows if row['stage'] == 'progress'),
            'blocked': sum(1 for row in enrollment_rows if row['stage'] == 'blocked'),
        },
    }
    return render(request, 'superadmin/user_detail.html', context)


@superadmin_required
def user_create(request):
    course_id = request.POST.get('course_id') or request.GET.get('course') or ''
    course_context = None
    if course_id:
        course_context = get_object_or_404(scope_courses(Course.objects.all(), request.academy), pk=course_id)

    initial = {}
    requested_role = (request.GET.get('role') or '').upper()
    if requested_role == 'PROFESSOR':
        initial['role'] = AcademyMembership.Role.PROFESSOR
    form = SuperadminUserCreationForm(request.POST or None, academy=request.academy, initial=initial)
    # La administración general de usuarios está reservada al equipo de la academia.
    # Los estudiantes se gestionan dentro de cada curso para no mezclar personas y matrículas.
    form.fields['role'].choices = [
        (AcademyMembership.Role.PROFESSOR, 'Profesor'),
        (AcademyMembership.Role.ADMIN, 'Administrador'),
    ]

    if request.method == 'POST' and form.is_valid():
        role = form.cleaned_data['role']
        if not academy_has_available_seat(request.academy, role):
            role_name = dict(AcademyMembership.Role.choices).get(role, 'usuarios').lower()
            messages.error(request, f'La licencia alcanzó el máximo de {role_name} permitido.')
            return render(request, 'superadmin/form.html', {
                'form': form,
                'title': 'Crear usuario',
                'subtitle': 'El cupo de este rol está completo. El propietario del sistema debe ampliar o cambiar el plan.',
                'back_url': 'superadmin:users',
                'back_href': reverse('superadmin:course_detail', kwargs={'course_id': course_context.id}) if course_context else '',
                'course_context': course_context,
            })
        user, membership, created = form.save(request.academy, approved_by=request.user)
        if course_context and membership.role in {AcademyMembership.Role.PROFESSOR, AcademyMembership.Role.ADMIN}:
            CourseInstructor.objects.get_or_create(course=course_context, user=user)
        log_event(request.user, 'usuario_creado', user, {'rol': membership.role, 'academia': request.academy.slug}, request)
        if not user.email_verified:
            try:
                send_verification_email(request, user, request.academy)
                messages.success(request, 'Usuario vinculado y correo de verificación enviado correctamente.')
            except Exception:
                messages.warning(request, 'Usuario vinculado. El correo de verificación no pudo enviarse en este momento.')
        elif not created:
            messages.success(request, 'El usuario existente fue vinculado a esta academia sin afectar sus otras academias.')
        else:
            messages.success(request, 'Usuario creado correctamente.')
        if course_context:
            messages.success(request, f'{user.display_name} quedó asociado a “{course_context.title}”.')
            return redirect('superadmin:course_detail', course_id=course_context.id)
        return redirect('superadmin:users')

    return render(request, 'superadmin/form.html', {
        'form': form,
        'title': 'Crear profesor para este curso' if course_context else 'Crear usuario',
        'subtitle': (
            f'El nuevo profesor quedará asociado directamente a “{course_context.title}”.'
            if course_context else f'El rol y el estado aplicarán únicamente dentro de {request.academy.name}.'
        ),
        'back_url': 'superadmin:users',
        'back_href': reverse('superadmin:course_detail', kwargs={'course_id': course_context.id}) if course_context else '',
        'course_context': course_context,
    })


@superadmin_required
def user_action(request, user_id):
    if request.method != 'POST':
        return redirect('superadmin:users')
    membership = get_object_or_404(AcademyMembership, academy=request.academy, user_id=user_id)
    user = get_object_or_404(User, pk=user_id, is_superuser=False)
    action = request.POST.get('action')
    if membership.role == AcademyMembership.Role.OWNER and user.pk != request.user.pk:
        messages.error(request, 'El dueño de la academia solo puede gestionarse desde Control del sistema.')
        return redirect('superadmin:users')
    if user.pk == request.user.pk and action in {'disable', 'reject', 'student', 'professor', 'admin'}:
        messages.error(request, 'No puedes bloquear tu propia membresía ni quitarte el rol de dueño.')
        return redirect('superadmin:users')
    if action in {'approve', 'approve_without_verification', 'enable'}:
        if action == 'approve' and not user.email_verified:
            messages.error(request, 'El correo todavía no está verificado. Puedes reenviar el enlace o usar “Aprobar sin verificar” si necesitas continuar.')
            return redirect('superadmin:users')
        if not academy_has_available_seat(request.academy, membership.role, exclude_membership=membership):
            messages.error(request, f'No hay cupos disponibles para {membership.get_role_display().lower()} en la licencia actual.')
            return redirect('superadmin:users')
        membership.status = AcademyMembership.Status.ACTIVE
        membership.approved_at = timezone.now()
        membership.approved_by_id = request.user.pk
        if action == 'approve_without_verification':
            if not request.academy.allow_unverified_approvals:
                messages.error(request, 'La aprobación sin verificación está desactivada en Perfil de la academia.')
                return redirect('superadmin:users')
            membership.email_verification_bypassed = True
        membership.save(update_fields=['status', 'approved_at', 'approved_by_id', 'email_verification_bypassed'])
        if action in {'approve', 'approve_without_verification'}:
            send_membership_approved_email(request, user, request.academy)
            if action == 'approve_without_verification':
                messages.success(request, 'Solicitud aprobada sin verificación de correo. La excepción solo aplica a esta academia; el usuario podrá verificar su correo más adelante.')
            else:
                messages.success(request, 'Cuenta habilitada. El acceso a cursos se controla por matrícula y pago.')
        else:
            messages.success(request, 'Acceso habilitado únicamente en esta academia.')
    elif action == 'disable':
        membership.status = AcademyMembership.Status.BLOCKED
        membership.save(update_fields=['status'])
        messages.warning(request, 'Acceso suspendido únicamente en esta academia.')
    elif action == 'reject':
        membership.status = AcademyMembership.Status.REJECTED
        membership.save(update_fields=['status'])
        messages.warning(request, 'Solicitud rechazada.')
    elif action in {'student', 'professor', 'admin'}:
        mapping = {
            'student': AcademyMembership.Role.STUDENT,
            'professor': AcademyMembership.Role.PROFESSOR,
            'admin': AcademyMembership.Role.ADMIN,
        }
        new_role = mapping[action]
        if membership.status == AcademyMembership.Status.ACTIVE and not academy_has_available_seat(request.academy, new_role, exclude_membership=membership):
            messages.error(request, f'No hay cupos disponibles para {dict(AcademyMembership.Role.choices).get(new_role, new_role).lower()}.')
            return redirect('superadmin:users')
        membership.role = new_role
        update_fields = ['role']
        if new_role not in {AcademyMembership.Role.PROFESSOR, AcademyMembership.Role.ADMIN}:
            membership.can_manage_student_payments = False
            update_fields.append('can_manage_student_payments')
        membership.save(update_fields=update_fields)
        messages.success(request, f'Rol actualizado a {membership.get_role_display()} solo en esta academia.')
    elif action == 'resend_verification':
        if user.email_verified:
            messages.info(request, 'El correo ya está verificado.')
        else:
            try:
                send_verification_email(request, user, request.academy)
                messages.success(request, 'Correo de verificación reenviado con la identidad de la academia.')
            except Exception as exc:
                messages.error(request, f'No se pudo enviar el correo de verificación: {exc}')
    elif action == 'verify':
        user.email_verified = True
        user.save(update_fields=['email_verified'])
        messages.success(request, 'Correo marcado como verificado.')
    log_event(request.user, f'usuario_{action}', user, {'membership': str(membership.id)}, request)
    return redirect('superadmin:users')


@superadmin_required
def courses(request):
    qs = scope_courses(Course.objects.all(), request.academy).select_related(
        'category', 'created_by', 'approved_by'
    ).prefetch_related('instructor_links__user').order_by('-updated_at')
    q = _query(request); status = request.GET.get('estado') or ''
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(category__name__icontains=q) | Q(created_by__email__icontains=q))
    if status:
        qs = qs.filter(status=status)
    course_rows = [_course_academic_summary(course) for course in qs[:200]]
    return render(request, 'superadmin/courses.html', {
        'course_rows': course_rows,
        'status_choices': Course.Status.choices,
        'q': q,
        'status_filter': status,
        'course_summary': {
            'total': len(course_rows),
            'published': sum(1 for row in course_rows if row['course'].status in {Course.Status.PUBLISHED, Course.Status.APPROVED}),
            'students': sum(row['total'] for row in course_rows),
            'completed': sum(row['completed'] for row in course_rows),
            'in_progress': sum(row['in_progress'] for row in course_rows),
        },
    })


@superadmin_required
def course_detail(request, course_id):
    course = get_object_or_404(
        scope_courses(Course.objects.all(), request.academy).select_related('category', 'created_by', 'approved_by').prefetch_related('instructor_links__user', 'modules__lessons'),
        pk=course_id,
    )
    if request.method == 'POST' and request.POST.get('action') == 'add_professor':
        professor_id = request.POST.get('professor_id')
        membership = AcademyMembership.objects.filter(
            academy=request.academy,
            user_id=professor_id,
            role__in=[AcademyMembership.Role.PROFESSOR, AcademyMembership.Role.ADMIN],
            status=AcademyMembership.Status.ACTIVE,
        ).first()
        if not membership:
            messages.error(request, 'Selecciona un profesor activo de esta academia.')
        else:
            professor = get_object_or_404(User, pk=membership.user_id)
            CourseInstructor.objects.get_or_create(course=course, user=professor)
            messages.success(request, f'{professor.display_name} fue asignado al curso.')
            log_event(request.user, 'profesor_asignado_curso', course, {'profesor': str(professor.pk)}, request)
        return redirect('superadmin:course_detail', course_id=course.id)

    summary = _course_academic_summary(course)
    course_payments = list(
        Payment.objects.filter(order__course=course)
        .select_related('order__user', 'order__course', 'approved_by')
        .order_by('-created_at')[:100]
    )
    course_users = _course_user_rows(course, request.academy, course_payments)
    # Evita duplicar profesores y estudiantes en varios bloques del mismo curso.
    # Profesores se gestionan en su sección propia; aquí quedan estudiantes y
    # solicitudes de estudiantes relacionadas con este curso.
    course_students = []
    for row in course_users:
        if row['relation'] == 'Profesor del curso':
            continue
        row['progress'] = progress_percentage(row['enrollment']) if row['enrollment'] else 0
        course_students.append(row)
    professor_ids = AcademyMembership.objects.filter(
        academy=request.academy,
        role=AcademyMembership.Role.PROFESSOR,
        status=AcademyMembership.Status.ACTIVE,
    ).values_list('user_id', flat=True)
    available_professors = User.objects.filter(pk__in=professor_ids, is_active=True).exclude(
        pk__in=course.instructor_links.values_list('user_id', flat=True)
    ).order_by('first_name', 'last_name', 'email')
    return render(request, 'superadmin/course_detail.html', {
        'course': course,
        'summary': summary,
        'available_professors': available_professors,
        'course_payments': course_payments,
        'course_students': course_students,
    })


@superadmin_required
def course_user_action(request, course_id, user_id):
    """Gestión básica del usuario sin salir del curso."""
    course = get_object_or_404(scope_courses(Course.objects.all(), request.academy), pk=course_id)
    if request.method != 'POST':
        return redirect('superadmin:course_detail', course_id=course.id)

    related = (
        course.instructor_links.filter(user_id=user_id).exists()
        or course.enrollments.filter(user_id=user_id).exists()
        or Payment.objects.filter(order__course=course, order__user_id=user_id).exists()
    )
    if not related:
        messages.error(request, 'Ese usuario no está asociado a este curso.')
        return redirect('superadmin:course_detail', course_id=course.id)

    membership = get_object_or_404(AcademyMembership, academy=request.academy, user_id=user_id)
    user = get_object_or_404(User, pk=user_id, is_superuser=False)
    action = request.POST.get('action')

    if action == 'resend_verification':
        if user.email_verified:
            messages.info(request, 'El correo de este usuario ya está verificado.')
        else:
            try:
                send_verification_email(request, user, request.academy)
                messages.success(request, f'Verificación reenviada a {user.email}.')
            except Exception as exc:
                messages.error(request, f'No se pudo reenviar la verificación: {exc}')
    elif action == 'disable':
        if user.pk == request.user.pk or membership.role == AcademyMembership.Role.OWNER:
            messages.error(request, 'No puedes suspender al dueño desde un curso.')
        else:
            membership.status = AcademyMembership.Status.BLOCKED
            membership.save(update_fields=['status'])
            messages.warning(request, f'Cuenta de {user.display_name} suspendida en esta academia.')
    elif action == 'enable':
        if not academy_has_available_seat(request.academy, membership.role, exclude_membership=membership):
            messages.error(request, f'No hay cupos disponibles para {membership.get_role_display().lower()}.')
        else:
            membership.status = AcademyMembership.Status.ACTIVE
            membership.save(update_fields=['status'])
            messages.success(request, f'Cuenta de {user.display_name} habilitada.')

    log_event(request.user, f'usuario_curso_{action}', user, {'curso': str(course.id)}, request)
    return redirect('superadmin:course_detail', course_id=course.id)


@superadmin_required
def course_professor_remove(request, course_id, user_id):
    if request.method != 'POST':
        return redirect('superadmin:course_detail', course_id=course_id)
    course = get_object_or_404(scope_courses(Course.objects.all(), request.academy), pk=course_id)
    link = get_object_or_404(CourseInstructor, course=course, user_id=user_id)
    professor_name = link.user.display_name
    link.delete()
    log_event(request.user, 'profesor_retirado_curso', course, {'profesor': str(user_id)}, request)
    messages.success(request, f'{professor_name} fue retirado del curso.')
    return redirect('superadmin:course_detail', course_id=course.id)


@superadmin_required
def course_action(request, course_id):
    course = get_object_or_404(scope_courses(Course.objects.all(), request.academy), pk=course_id)
    if request.method != 'POST':
        return redirect('superadmin:course_detail', course_id=course.id)
    action = request.POST.get('action')
    now = timezone.now()
    if action == 'publish':
        course.status = Course.Status.PUBLISHED
        course.approved_by = request.user
        course.approved_at = now
        course.published_at = now
        course.save(update_fields=['status', 'approved_by', 'approved_at', 'published_at', 'updated_at'])
        messages.success(request, f'“{course.title}” fue aprobado y publicado.')
    elif action == 'changes':
        course.status = Course.Status.CHANGES
        course.save(update_fields=['status', 'updated_at'])
        messages.warning(request, 'Curso devuelto para cambios.')
    elif action == 'pause':
        course.status = Course.Status.PAUSED
        course.save(update_fields=['status', 'updated_at'])
        messages.warning(request, 'Curso pausado.')
    elif action == 'archive':
        course.status = Course.Status.ARCHIVED
        course.save(update_fields=['status', 'updated_at'])
        messages.info(request, 'Curso archivado.')
    log_event(request.user, f'curso_{action}', course, request=request)
    return redirect('superadmin:course_detail', course_id=course.id)


@superadmin_required
def course_payment_action(request, course_id, payment_id):
    course = get_object_or_404(scope_courses(Course.objects.all(), request.academy), pk=course_id)
    if request.method != 'POST':
        return redirect('superadmin:course_detail', course_id=course.id)
    payment = get_object_or_404(
        Payment.objects.select_related('order__user', 'order__course'),
        pk=payment_id,
        order__course=course,
    )
    action = request.POST.get('action')
    if action == 'approve' and payment.status == Payment.Status.PENDING:
        enrollment = approve_payment(payment, request.user)
        messages.success(request, f'Pago aprobado. {enrollment.user.display_name} ya tiene acceso a “{course.title}”.')
    elif action == 'reject' and payment.status == Payment.Status.PENDING:
        payment.status = Payment.Status.REJECTED
        payment.approved_by = request.user
        payment.approved_at = timezone.now()
        payment.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        messages.warning(request, f'Comprobante de {payment.order.user.display_name} rechazado.')
    log_event(request.user, f'pago_curso_{action}', payment, {'curso': str(course.id)}, request)
    if request.POST.get('return_to') == 'students':
        return redirect('superadmin:student_course_users', course_id=course.id)
    return redirect('superadmin:course_detail', course_id=course.id)


@superadmin_required
def course_enrollment_create(request, course_id):
    course = get_object_or_404(scope_courses(Course.objects.all(), request.academy), pk=course_id)
    form = EnrollmentCreateForm(request.POST or None, academy=request.academy, fixed_course=course)
    if request.method == 'POST' and form.is_valid():
        enrollment = form.save()
        log_event(request.user, 'matricula_manual_creada', enrollment, {'curso': str(course.id)}, request)
        messages.success(request, f'Acceso habilitado para {enrollment.user.display_name} en “{course.title}”.')
        return redirect('superadmin:course_detail', course_id=course.id)
    return render(request, 'superadmin/form.html', {
        'form': form,
        'title': 'Habilitar acceso a este curso',
        'subtitle': f'{course.title} · selecciona un estudiante activo de esta academia.',
        'back_href': reverse('superadmin:course_detail', kwargs={'course_id': course.id}),
    })


@superadmin_required
def payments(request):
    qs = _payments_for(request.academy).select_related('order__user', 'order__course', 'approved_by').order_by('-created_at')
    status = request.GET.get('estado') or ''; q = _query(request)
    if status: qs = qs.filter(status=status)
    if q: qs = qs.filter(Q(order__code__icontains=q) | Q(order__user__email__icontains=q) | Q(reference__icontains=q) | Q(order__course__title__icontains=q))
    totals = {'approved': _payments_for(request.academy).filter(status=Payment.Status.APPROVED).aggregate(total=Sum('amount'))['total'] or Decimal('0'), 'pending': _payments_for(request.academy).filter(status=Payment.Status.PENDING).count()}
    return render(request, 'superadmin/payments.html', {'payments_list': qs[:250], 'status_choices': Payment.Status.choices, 'totals': totals, 'q': q, 'status_filter': status})


@superadmin_required
def payment_action(request, payment_id):
    payment = get_object_or_404(
        _payments_for(request.academy).select_related('order__user', 'order__course'),
        pk=payment_id,
    )
    course = payment.order.course
    if request.method != 'POST':
        return redirect('superadmin:course_detail', course_id=course.id)
    action = request.POST.get('action')
    if action == 'approve' and payment.status == Payment.Status.PENDING:
        enrollment = approve_payment(payment, request.user)
        messages.success(request, f'Pago aprobado. {enrollment.user.display_name} ya tiene acceso a “{course.title}”.')
    elif action == 'reject' and payment.status == Payment.Status.PENDING:
        payment.status = Payment.Status.REJECTED
        payment.approved_by = request.user
        payment.approved_at = timezone.now()
        payment.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        messages.warning(request, f'Comprobante de {payment.order.user.display_name} rechazado.')
    log_event(request.user, f'pago_curso_{action}', payment, {'curso': str(course.id)}, request)
    return redirect('superadmin:course_detail', course_id=course.id)


@superadmin_required
def enrollments(request):
    qs = _enrollments_for(request.academy).select_related('user', 'course').order_by('-created_at')
    q = _query(request)
    status = request.GET.get('estado') or ''
    if q:
        qs = qs.filter(Q(user__email__icontains=q) | Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q) | Q(course__title__icontains=q))
    if status:
        qs = qs.filter(status=status)
    rows = [_enrollment_progress_row(item) for item in qs[:250]]
    summary = {
        'total': len(rows),
        'active': sum(1 for row in rows if row['enrollment'].status == Enrollment.Status.ACTIVE),
        'completed': sum(1 for row in rows if row['stage'] == 'completed'),
        'blocked': sum(1 for row in rows if row['stage'] == 'blocked'),
    }
    return render(request, 'superadmin/enrollments.html', {
        'enrollment_rows': rows,
        'q': q,
        'status_filter': status,
        'status_choices': Enrollment.Status.choices,
        'summary': summary,
    })


@superadmin_required
def enrollment_create(request):
    form = EnrollmentCreateForm(request.POST or None, academy=request.academy)
    if request.method == 'POST' and form.is_valid():
        enrollment = form.save()
        log_event(request.user, 'matricula_manual_creada', enrollment, {'curso': str(enrollment.course_id)}, request)
        messages.success(request, f'Acceso habilitado para {enrollment.user.display_name} en “{enrollment.course.title}”.')
        return redirect('superadmin:enrollments')
    return render(request, 'superadmin/form.html', {
        'form': form,
        'title': 'Habilitar acceso a un curso',
        'subtitle': 'Esto no crea una cuenta: vincula un estudiante activo de esta academia con un curso concreto.',
        'back_url': 'superadmin:enrollments',
    })


@superadmin_required
def enrollment_edit(request, enrollment_id):
    enrollment = get_object_or_404(_enrollments_for(request.academy).select_related('user', 'course'), pk=enrollment_id)
    form = EnrollmentEditForm(request.POST or None, instance=enrollment)
    if request.method == 'POST' and form.is_valid(): form.save(); log_event(request.user, 'matricula_actualizada', enrollment, request=request); messages.success(request, 'Acceso actualizado.'); return redirect('superadmin:enrollments')
    return render(request, 'superadmin/form.html', {'form': form, 'title': 'Editar matrícula', 'subtitle': f'{enrollment.user.display_name} · {enrollment.course.title}', 'back_url': 'superadmin:enrollments'})


@superadmin_required
def certificates(request):
    """Entrada ordenada por curso al control de certificados."""
    courses_qs = (
        scope_courses(Course.objects.filter(certificate_enabled=True), request.academy)
        .select_related('category')
        .order_by('title')
    )
    course_rows = []
    for course in courses_qs:
        enrollments = list(course.enrollments.select_related('user').all())
        enrollment_ids = [item.id for item in enrollments]
        certs = list(
            Certificate.objects.filter(enrollment_id__in=enrollment_ids)
            .select_related('enrollment__user')
        )
        issued_ids = {item.enrollment_id for item in certs}
        completed = sum(
            1 for item in enrollments
            if item.status == Enrollment.Status.COMPLETED or item.certified_at or progress_percentage(item) >= 100
        )
        course_rows.append({
            'course': course,
            'students': len(enrollments),
            'completed': completed,
            'issued': len(certs),
            'valid': sum(1 for item in certs if item.status == Certificate.Status.VALID),
            'pending': max(completed - len(issued_ids), 0),
        })
    return render(request, 'superadmin/certificates.html', {
        'course_rows': course_rows,
        'total_certificates': sum(row['issued'] for row in course_rows),
        'total_pending': sum(row['pending'] for row in course_rows),
    })


@superadmin_required
def certificate_course_detail(request, course_id):
    course = get_object_or_404(
        scope_courses(Course.objects.filter(certificate_enabled=True), request.academy)
        .select_related('category'),
        pk=course_id,
    )
    enrollments = list(
        course.enrollments.select_related('user').order_by('user__first_name', 'user__last_name', 'user__email')
    )
    certificates_by_enrollment = {
        item.enrollment_id: item
        for item in Certificate.objects.filter(enrollment__course=course).select_related('enrollment__user')
    }
    rows = []
    for enrollment in enrollments:
        progress = progress_percentage(enrollment)
        completed = bool(
            enrollment.status == Enrollment.Status.COMPLETED
            or enrollment.certified_at
            or progress >= 100
        )
        certificate = certificates_by_enrollment.get(enrollment.id)
        rows.append({
            'enrollment': enrollment,
            'progress': progress,
            'completed': completed,
            'certificate': certificate,
        })
    issued = [row for row in rows if row['certificate']]
    return render(request, 'superadmin/certificate_course.html', {
        'course': course,
        'rows': rows,
        'stats': {
            'students': len(rows),
            'completed': sum(1 for row in rows if row['completed']),
            'issued': len(issued),
            'valid': sum(1 for row in issued if row['certificate'].status == Certificate.Status.VALID),
            'pending': sum(1 for row in rows if row['completed'] and not row['certificate']),
        },
    })


@superadmin_required
def categories(request):
    qs = scope_categories(Category.objects.all(), request.academy).select_related('parent').order_by('order', 'name')
    return render(request, 'superadmin/categories.html', {'categories_list': qs})


@superadmin_required
def category_create(request):
    form = CategoryForm(request.POST or None, academy=request.academy)
    if request.method == 'POST' and form.is_valid():
        category, created = create_academy_category(
            request.academy,
            form.cleaned_data['name'],
            description=form.cleaned_data.get('description', ''),
            parent=form.cleaned_data.get('parent'),
            is_active=form.cleaned_data.get('is_active', True),
            order=form.cleaned_data.get('order', 0),
        )
        if not created:
            form.add_error('name', 'Ya existe una categoría con este nombre en la academia.')
        else:
            log_event(request.user, 'categoria_creada', category, request=request)
            messages.success(request, 'Categoría creada y sincronizada con los profesores.')
            return redirect('superadmin:categories')
    return render(request, 'superadmin/form.html', {'form': form, 'title': 'Crear categoría', 'subtitle': 'La categoría solo pertenecerá a esta academia.', 'back_url': 'superadmin:categories'})


@superadmin_required
def banks(request):
    academy = request.academy
    settings_form = AcademyPaymentSettingsForm(request.POST or None, instance=academy, prefix='payment')
    if request.method == 'POST' and request.POST.get('section') == 'payment_settings':
        if settings_form.is_valid():
            settings_form.save()
            log_event(request.user, 'metodos_pago_actualizados', academy, request=request)
            messages.success(request, 'Métodos de pago actualizados para esta academia.')
            return redirect('superadmin:banks')
    banks_qs = scope_banks(BankAccount.objects.all(), academy).order_by('order', 'bank_name')
    return render(request, 'superadmin/banks.html', {
        'banks_list': banks_qs,
        'payment_settings_form': settings_form,
        'academy': academy,
    })


@superadmin_required
def bank_create(request):
    form = BankAccountForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        bank = form.save()
        bind_bank(bank, request.academy)
        log_event(request.user, 'cuenta_bancaria_creada', bank, request=request)
        messages.success(request, 'Cuenta bancaria creada para esta academia.')
        return redirect('superadmin:banks')
    return render(request, 'superadmin/form.html', {
        'form': form, 'title': 'Crear cuenta bancaria',
        'subtitle': 'Solo la verán estudiantes de esta academia al pagar un curso.',
        'back_url': 'superadmin:banks',
    })


@superadmin_required
def bank_edit(request, bank_id):
    bank = get_object_or_404(scope_banks(BankAccount.objects.all(), request.academy), pk=bank_id)
    form = BankAccountForm(request.POST or None, instance=bank)
    if request.method == 'POST' and form.is_valid():
        form.save()
        log_event(request.user, 'cuenta_bancaria_actualizada', bank, request=request)
        messages.success(request, 'Cuenta bancaria actualizada.')
        return redirect('superadmin:banks')
    return render(request, 'superadmin/form.html', {
        'form': form, 'title': 'Editar cuenta bancaria',
        'subtitle': 'Los cambios solo afectan a esta academia.',
        'back_url': 'superadmin:banks',
    })


@superadmin_required
def bank_toggle(request, bank_id):
    if request.method != 'POST':
        return redirect('superadmin:banks')
    bank = get_object_or_404(scope_banks(BankAccount.objects.all(), request.academy), pk=bank_id)
    bank.is_active = not bank.is_active
    bank.save(update_fields=['is_active'])
    log_event(request.user, 'cuenta_bancaria_visibilidad', bank, {'visible': bank.is_active}, request)
    messages.success(request, 'Visibilidad de la cuenta actualizada.')
    return redirect('superadmin:banks')


@superadmin_required
def audit(request):
    logs = AuditLog.objects.select_related('actor').filter(metadata___academy_id=str(request.academy.id))[:300]
    return render(request, 'superadmin/audit.html', {'logs': logs})


@superadmin_required
def owner_profile(request):
    academy = request.academy
    section = request.POST.get('section') if request.method == 'POST' else ''
    branding_form = AcademyBrandingForm(
        request.POST if section == 'branding' else None,
        request.FILES if section == 'branding' else None,
        instance=academy,
        prefix='branding',
    )
    support_form = AcademySupportSettingsForm(
        request.POST if section == 'support' else None,
        instance=academy,
        prefix='support',
    )

    if request.method == 'POST' and section == 'branding' and branding_form.is_valid():
        branding_form.save()
        log_event(request.user, 'academia_perfil_actualizado', academy, {'slug': academy.slug}, request)
        messages.success(request, 'Perfil y personalización de la academia actualizados.')
        return redirect('superadmin:owner_profile')

    if request.method == 'POST' and section == 'support' and support_form.is_valid():
        support_form.save()
        log_event(request.user, 'academia_soporte_actualizado', academy, request=request)
        messages.success(request, 'Contactos de soporte de la academia actualizados.')
        return redirect('superadmin:owner_profile')

    return render(request, 'superadmin/owner_profile.html', {
        'academy': academy,
        'branding_form': branding_form,
        'support_form': support_form,
        'public_url': f'/academy/{academy.slug}/',
    })


@superadmin_required
def certificate_style(request):
    academy = request.academy
    form = AcademyCertificateStyleForm(request.POST or None, request.FILES or None, instance=academy)
    if request.method == 'POST' and form.is_valid():
        form.save()
        log_event(request.user, 'estilo_certificado_actualizado', academy, request=request)
        messages.success(request, 'Diseño predeterminado de certificados actualizado.')
        return redirect('superadmin:certificate_style')
    return render(request, 'superadmin/certificate_style.html', {
        'form': form,
        'academy': academy,
        'certificate_preview': preview_style_context(None, academy),
    })


@superadmin_required
def certificate_style_preview(request):
    academy = request.academy
    # Para la vista previa global usamos un objeto ligero con los atributos mínimos.
    class PreviewCourse:
        title = 'Curso de ejemplo'
        certificate_style_mode = Course.CertificateStyleMode.ACADEMY
    buf = render_certificate_pdf(
        academy, PreviewCourse(), 'Nombre del estudiante', code='VISTA-PREVIA', issued_at=timezone.now()
    )
    return FileResponse(buf, content_type='application/pdf', as_attachment=False, filename='vista-previa-certificado.pdf')


@superadmin_required
def branding(request):
    form = AcademyBrandingForm(request.POST or None, request.FILES or None, instance=request.academy)
    if request.method == 'POST' and form.is_valid():
        academy = form.save()
        log_event(request.user, 'academia_personalizacion_actualizada', academy, {'slug': academy.slug}, request)
        messages.success(request, 'Personalización pública actualizada correctamente.')
        return redirect('superadmin:branding')
    return render(request, 'superadmin/branding.html', {
        'form': form,
        'academy': request.academy,
        'public_url': f'/academy/{request.academy.slug}/',
    })


@superadmin_required
def smtp_settings(request):
    academy = request.academy
    action = request.POST.get('action') if request.method == 'POST' else ''

    if request.method == 'POST' and action in {'default', 'disable'}:
        academy.smtp_enabled = False
        academy.save(update_fields=['smtp_enabled', 'updated_at'])
        log_event(request.user, 'correo_predeterminado_activado', academy, request=request)
        messages.success(request, 'Configuración predeterminada activada. DevLayer Studio enviará automáticamente las verificaciones y notificaciones de esta academia.')
        return redirect('superadmin:smtp_settings')

    form = AcademySMTPForm(request.POST or None, academy=academy)
    if request.method == 'POST' and action in {'save', 'test'} and form.is_valid():
        academy = form.save()
        log_event(request.user, 'smtp_academia_actualizado', academy, {'host': academy.smtp_host, 'port': academy.smtp_port}, request)
        if action == 'test':
            recipient = form.cleaned_data['test_email']
            try:
                send_academy_mail(
                    academy,
                    subject=f'Prueba de correo · {academy.name}',
                    message=f'Prueba de configuración SMTP de {academy.name}.\n\nSi recibiste este mensaje, el servidor SMTP está funcionando correctamente.',
                    recipients=[recipient],
                    fail_silently=False,
                    html_message=(
                        f'<div style="font-family:Arial,sans-serif;color:#172033">'
                        f'<img src="cid:academy-logo" alt="{academy.name}" style="display:block;max-width:180px;max-height:64px;object-fit:contain;margin-bottom:18px">'
                        f'<h2 style="margin:0 0 12px">Prueba de correo · {academy.name}</h2>'
                        f'<p>Esta es una prueba del servidor SMTP configurado para tu academia.</p>'
                        f'<p><strong>Resultado:</strong> envío correcto.</p>'
                        f'</div>'
                    ),
                    attach_brand_logo=True,
                )
                messages.success(request, f'Dominio propio guardado. Prueba enviada correctamente a {recipient}.')
            except Exception as exc:
                messages.error(request, f'El dominio propio se guardó, pero la prueba falló: {exc}')
        else:
            messages.success(request, 'Dominio propio guardado. La contraseña SMTP permanece cifrada.')
        return redirect('superadmin:smtp_settings')

    return render(request, 'superadmin/smtp_settings.html', {
        'form': form,
        'academy': academy,
        'using_default_mail': not academy.smtp_configured,
        'platform_mail_ready': platform_mail_available(),
    })
