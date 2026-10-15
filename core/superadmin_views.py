from decimal import Decimal

from django.contrib import messages
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.models import User
from accounts.services import send_verification_email
from audit.models import AuditLog
from audit.services import log_event
from billing.models import BankAccount, Payment
from billing.services import approve_payment
from catalog.models import Category, Course
from certificates.models import Certificate
from learning.models import Enrollment

from .decorators import superadmin_required
from .superadmin_forms import BankAccountForm, CategoryForm, EnrollmentEditForm, SuperadminUserCreationForm


def _query(request):
    return (request.GET.get('q') or '').strip()


@superadmin_required
def dashboard(request):
    approved_revenue = Payment.objects.filter(status=Payment.Status.APPROVED).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    context = {
        'stats': {
            'students': User.objects.filter(role=User.Role.STUDENT).count(),
            'professors': User.objects.filter(role=User.Role.PROFESSOR).count(),
            'courses': Course.objects.count(),
            'pending_courses': Course.objects.filter(status__in=[Course.Status.REVIEW, Course.Status.APPROVED]).count(),
            'active_enrollments': Enrollment.objects.filter(status=Enrollment.Status.ACTIVE).count(),
            'pending_payments': Payment.objects.filter(status=Payment.Status.PENDING).count(),
            'certificates': Certificate.objects.filter(status=Certificate.Status.VALID).count(),
            'revenue': approved_revenue,
        },
        'recent_courses': Course.objects.select_related('category', 'created_by').order_by('-updated_at')[:6],
        'recent_payments': Payment.objects.select_related('order__user', 'order__course').order_by('-created_at')[:6],
        'recent_users': User.objects.order_by('-date_joined')[:6],
    }
    return render(request, 'superadmin/dashboard.html', context)


@superadmin_required
def users(request):
    qs = User.objects.all().order_by('-date_joined')
    q = _query(request)
    role = request.GET.get('rol') or ''
    state = request.GET.get('estado') or ''
    if q:
        qs = qs.filter(Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))
    if role:
        qs = qs.filter(role=role)
    if state == 'activo':
        qs = qs.filter(is_active=True)
    elif state == 'bloqueado':
        qs = qs.filter(is_active=False)
    return render(request, 'superadmin/users.html', {'users_list': qs[:200], 'roles': User.Role.choices, 'q': q, 'role_filter': role, 'state_filter': state})


@superadmin_required
def user_create(request):
    form = SuperadminUserCreationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        log_event(request.user, 'usuario_creado', user, {'rol': user.role}, request)
        if not user.email_verified:
            try:
                send_verification_email(request, user)
                messages.success(request, 'Usuario creado y correo de verificación enviado.')
            except Exception:
                messages.warning(request, 'Usuario creado. No se pudo enviar el correo de verificación; revisa el SMTP.')
        else:
            messages.success(request, 'Usuario creado correctamente.')
        return redirect('superadmin:users')
    return render(request, 'superadmin/form.html', {'form': form, 'title': 'Crear usuario', 'subtitle': 'Crea profesores, estudiantes o administradores sin entrar al panel técnico de Django.', 'back_url': 'superadmin:users'})


@superadmin_required
def user_action(request, user_id):
    if request.method != 'POST':
        return redirect('superadmin:users')
    user = get_object_or_404(User, pk=user_id)
    action = request.POST.get('action')
    if user.is_superuser and action in {'disable', 'student', 'professor'}:
        messages.error(request, 'No se puede modificar el rol o desactivar al superadministrador principal desde esta acción.')
        return redirect('superadmin:users')
    if action == 'enable':
        user.is_active = True
        user.save(update_fields=['is_active'])
        messages.success(request, 'Usuario habilitado.')
    elif action == 'disable':
        user.is_active = False
        user.save(update_fields=['is_active'])
        messages.warning(request, 'Usuario deshabilitado. No podrá iniciar sesión.')
    elif action in {'student', 'professor', 'admin'}:
        mapping = {'student': User.Role.STUDENT, 'professor': User.Role.PROFESSOR, 'admin': User.Role.ADMIN}
        user.role = mapping[action]
        user.save(update_fields=['role'])
        messages.success(request, f'Rol actualizado a {user.get_role_display()}.')
    elif action == 'verify':
        user.email_verified = True
        user.save(update_fields=['email_verified'])
        messages.success(request, 'Correo marcado como verificado.')
    log_event(request.user, f'usuario_{action}', user, request=request)
    return redirect('superadmin:users')


@superadmin_required
def courses(request):
    qs = Course.objects.select_related('category', 'created_by', 'approved_by').prefetch_related('instructor_links__user').order_by('-updated_at')
    q = _query(request)
    status = request.GET.get('estado') or ''
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(category__name__icontains=q) | Q(created_by__email__icontains=q))
    if status:
        qs = qs.filter(status=status)
    return render(request, 'superadmin/courses.html', {'courses_list': qs[:200], 'status_choices': Course.Status.choices, 'q': q, 'status_filter': status})


@superadmin_required
def course_action(request, course_id):
    if request.method != 'POST':
        return redirect('superadmin:courses')
    course = get_object_or_404(Course, pk=course_id)
    action = request.POST.get('action')
    now = timezone.now()
    if action == 'publish':
        course.status = Course.Status.PUBLISHED
        course.approved_by = request.user
        course.approved_at = now
        course.published_at = now
        course.save(update_fields=['status', 'approved_by', 'approved_at', 'published_at', 'updated_at'])
        messages.success(request, f'“{course.title}” fue aprobado y publicado. Ya aparece en el catálogo.')
    elif action == 'changes':
        course.status = Course.Status.CHANGES
        course.save(update_fields=['status', 'updated_at'])
        messages.warning(request, 'Curso devuelto al profesor para cambios.')
    elif action == 'pause':
        course.status = Course.Status.PAUSED
        course.save(update_fields=['status', 'updated_at'])
        messages.warning(request, 'Curso pausado.')
    elif action == 'archive':
        course.status = Course.Status.ARCHIVED
        course.save(update_fields=['status', 'updated_at'])
        messages.info(request, 'Curso archivado.')
    log_event(request.user, f'curso_{action}', course, request=request)
    return redirect('superadmin:courses')


@superadmin_required
def payments(request):
    qs = Payment.objects.select_related('order__user', 'order__course', 'approved_by').order_by('-created_at')
    status = request.GET.get('estado') or ''
    q = _query(request)
    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(Q(order__code__icontains=q) | Q(order__user__email__icontains=q) | Q(reference__icontains=q) | Q(order__course__title__icontains=q))
    totals = {
        'approved': Payment.objects.filter(status=Payment.Status.APPROVED).aggregate(total=Sum('amount'))['total'] or Decimal('0'),
        'pending': Payment.objects.filter(status=Payment.Status.PENDING).count(),
    }
    return render(request, 'superadmin/payments.html', {'payments_list': qs[:250], 'status_choices': Payment.Status.choices, 'totals': totals, 'q': q, 'status_filter': status})


@superadmin_required
def payment_action(request, payment_id):
    if request.method != 'POST':
        return redirect('superadmin:payments')
    payment = get_object_or_404(Payment.objects.select_related('order__user', 'order__course'), pk=payment_id)
    action = request.POST.get('action')
    if action == 'approve':
        approve_payment(payment, request.user)
        messages.success(request, f'Pago {payment.order.code} aprobado. El curso se habilitó automáticamente.')
    elif action == 'reject':
        payment.status = Payment.Status.REJECTED
        payment.approved_by = request.user
        payment.approved_at = timezone.now()
        payment.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        messages.warning(request, f'Pago {payment.order.code} rechazado.')
    log_event(request.user, f'pago_{action}', payment, request=request)
    return redirect('superadmin:payments')


@superadmin_required
def enrollments(request):
    qs = Enrollment.objects.select_related('user', 'course').order_by('-created_at')
    q = _query(request)
    if q:
        qs = qs.filter(Q(user__email__icontains=q) | Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q) | Q(course__title__icontains=q))
    return render(request, 'superadmin/enrollments.html', {'enrollments_list': qs[:250], 'q': q})


@superadmin_required
def enrollment_edit(request, enrollment_id):
    enrollment = get_object_or_404(Enrollment.objects.select_related('user', 'course'), pk=enrollment_id)
    form = EnrollmentEditForm(request.POST or None, instance=enrollment)
    if request.method == 'POST' and form.is_valid():
        form.save()
        log_event(request.user, 'matricula_actualizada', enrollment, request=request)
        messages.success(request, 'Acceso del estudiante actualizado.')
        return redirect('superadmin:enrollments')
    return render(request, 'superadmin/form.html', {'form': form, 'title': 'Editar matrícula', 'subtitle': f'{enrollment.user.display_name} · {enrollment.course.title}', 'back_url': 'superadmin:enrollments'})


@superadmin_required
def certificates(request):
    qs = Certificate.objects.select_related('enrollment__user', 'enrollment__course').order_by('-issued_at')
    return render(request, 'superadmin/certificates.html', {'certificates_list': qs[:250]})


@superadmin_required
def categories(request):
    return render(request, 'superadmin/categories.html', {'categories_list': Category.objects.select_related('parent').order_by('order', 'name')})


@superadmin_required
def category_create(request):
    form = CategoryForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        category = form.save()
        log_event(request.user, 'categoria_creada', category, request=request)
        messages.success(request, 'Categoría creada correctamente.')
        return redirect('superadmin:categories')
    return render(request, 'superadmin/form.html', {'form': form, 'title': 'Crear categoría', 'subtitle': 'Organiza el catálogo por áreas y subcategorías.', 'back_url': 'superadmin:categories'})


@superadmin_required
def banks(request):
    return render(request, 'superadmin/banks.html', {'banks_list': BankAccount.objects.order_by('order', 'bank_name')})


@superadmin_required
def bank_create(request):
    form = BankAccountForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        bank = form.save()
        log_event(request.user, 'cuenta_bancaria_creada', bank, request=request)
        messages.success(request, 'Cuenta bancaria creada.')
        return redirect('superadmin:banks')
    return render(request, 'superadmin/form.html', {'form': form, 'title': 'Crear cuenta bancaria', 'subtitle': 'Esta información se muestra al estudiante cuando elige transferencia.', 'back_url': 'superadmin:banks'})


@superadmin_required
def audit(request):
    logs = AuditLog.objects.select_related('actor').all()[:300]
    return render(request, 'superadmin/audit.html', {'logs': logs})
