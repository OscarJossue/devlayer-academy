from datetime import timedelta
import mimetypes
import secrets
import string
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.db import models
from django.db.models import Q, Sum
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.forms import EmailAuthenticationForm
from accounts.models import User
from accounts.services import send_verification_email
from billing.models import Order, Payment
from catalog.models import Category, Course
from core.decorators import platform_owner_required
from core.fields import _fernet

from .forms import AcademyCreateForm, AcademyEditForm, AcademyOwnerForm, AcademyPlanForm, LicenseForm, PlatformSMTPForm
from .models import Academy, AcademyLicense, AcademyMembership, AcademyPlan, PlatformAuditLog, PlatformEmailSettings
from .services import academy_course_ids, academy_for_user, academy_license_usage, academy_user_ids, current_academy_from_session, log_platform_event, membership_for_user, scope_categories, scope_courses
from .mail import platform_mail_available, send_platform_mail


class SystemOwnerLoginView(auth_views.LoginView):
    template_name = 'tenancy/system_login.html'
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = False

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_superuser:
            return redirect('tenancy:system_dashboard')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.get_user()
        if not user.is_superuser:
            form.add_error(None, 'Esta entrada es exclusiva del administrador maestro de la plataforma.')
            return self.form_invalid(form)
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('tenancy:system_dashboard')


def _platform_financials(academies):
    licenses = [a.current_license for a in academies if a.current_license]
    contracted = sum((item.price or Decimal('0')) for item in licenses)
    collected = sum((item.amount_paid or Decimal('0')) for item in licenses)
    receivable = sum((item.balance_due for item in licenses), Decimal('0'))
    daily = sum((item.daily_cost for item in licenses if item.is_valid), Decimal('0'))
    return {
        'contracted': contracted,
        'collected': collected,
        'receivable': receivable,
        'daily': daily,
    }


@platform_owner_required
def system_dashboard(request):
    academies = list(Academy.objects.select_related('license').all())
    active = sum(1 for item in academies if item.access_enabled)
    today = timezone.localdate()
    expiring_7 = sum(
        1 for a in academies
        if a.current_license and a.current_license.ends_at
        and 0 <= (a.current_license.ends_at - today).days <= 7
    )
    expiring_30 = sum(
        1 for a in academies
        if a.current_license and a.current_license.ends_at
        and 0 <= (a.current_license.ends_at - today).days <= 30
    )
    context = {
        'stats': {
            'academies': len(academies),
            'active': active,
            'blocked': len(academies) - active,
            'users': AcademyMembership.objects.count(),
            'courses': sum(a.course_bindings.count() for a in academies),
            'plans': AcademyPlan.objects.filter(is_active=True).count(),
            'expiring_7': expiring_7,
            'expiring_30': expiring_30,
        },
        'finance': _platform_financials(academies),
        'academies_recent': academies[:8],
        'expiring': sorted(
            [a for a in academies if a.current_license and a.current_license.ends_at],
            key=lambda a: a.current_license.ends_at,
        )[:8],
        'events': PlatformAuditLog.objects.select_related('academy')[:10],
        'plans_recent': AcademyPlan.objects.order_by('price', 'name')[:6],
    }
    return render(request, 'tenancy/system_dashboard.html', context)


@platform_owner_required
def system_finances(request):
    academies = list(Academy.objects.select_related('license').all())
    rows = []
    for academy in academies:
        license_obj = academy.current_license
        if not license_obj:
            continue
        owner_id = AcademyMembership.objects.filter(academy=academy, role=AcademyMembership.Role.OWNER).values_list('user_id', flat=True)
        owner = User.objects.filter(pk__in=owner_id, is_superuser=False).first()
        rows.append({'academy': academy, 'license': license_obj, 'owner': owner})
    rows.sort(key=lambda x: (x['license'].ends_at is None, x['license'].ends_at or timezone.localdate()))
    return render(request, 'tenancy/system_finances.html', {
        'rows': rows,
        'finance': _platform_financials(academies),
    })


@platform_owner_required
def plan_list(request):
    plans = AcademyPlan.objects.annotate(license_count=models.Count('licenses')).order_by('price', 'name')
    return render(request, 'tenancy/plan_list.html', {'plans': plans})


@platform_owner_required
def plan_create(request):
    form = AcademyPlanForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        plan = form.save()
        log_platform_event(request.user, 'plan_creado', metadata={'plan': plan.name, 'precio': str(plan.price)})
        messages.success(request, f'Plan “{plan.name}” creado correctamente.')
        return redirect('tenancy:plan_list')
    return render(request, 'tenancy/plan_form.html', {
        'form': form, 'title': 'Nuevo plan',
        'subtitle': 'Define precio, duración y cupos. Estos valores se copiarán a cada licencia nueva.',
    })


@platform_owner_required
def plan_edit(request, plan_id):
    plan = get_object_or_404(AcademyPlan, pk=plan_id)
    form = AcademyPlanForm(request.POST or None, instance=plan)
    if request.method == 'POST' and form.is_valid():
        form.save()
        log_platform_event(request.user, 'plan_actualizado', metadata={'plan': plan.name})
        messages.success(request, 'Plan actualizado. Las licencias existentes conservan sus condiciones hasta que cambies su plan manualmente.')
        return redirect('tenancy:plan_list')
    return render(request, 'tenancy/plan_form.html', {
        'form': form, 'title': f'Editar plan · {plan.name}',
        'subtitle': 'Los cambios aplican a nuevas licencias y a licencias donde vuelvas a seleccionar este plan.',
        'plan': plan,
    })


@platform_owner_required
def academy_list(request):
    q = (request.GET.get('q') or '').strip()
    qs = Academy.objects.select_related('license').all()
    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(contact_email__icontains=q)
            | Q(legal_name__icontains=q)
            | Q(slug__icontains=q)
        )
    rows = []
    for academy in qs:
        owner_ids = academy_user_ids(academy, roles=[AcademyMembership.Role.OWNER])
        owner = User.objects.filter(pk__in=owner_ids, is_superuser=False).first()
        usage = academy_license_usage(academy)
        rows.append({
            'academy': academy,
            'owner': owner,
            'users': AcademyMembership.objects.filter(academy=academy).count(),
            'courses': academy.course_bindings.count(),
            'usage': usage,
        })
    return render(request, 'tenancy/academy_list.html', {'rows': rows, 'q': q})


def _owner_credentials_key(academy):
    return f'owner_credentials_{academy.pk}'


def _stash_owner_credentials(request, academy, user, password):
    # Se conserva únicamente durante el redirect inmediato y cifrada con la
    # misma clave de contenido del sistema. academy_detail hace pop() y borra
    # el valor en cuanto se muestra.
    token = _fernet().encrypt(password.encode()).decode()
    request.session[_owner_credentials_key(academy)] = {
        'email': user.email,
        'password_token': token,
    }
    request.session.modified = True


def _pop_owner_credentials(request, academy):
    payload = request.session.pop(_owner_credentials_key(academy), None)
    request.session.modified = True
    if not payload:
        return None
    try:
        password = _fernet().decrypt(payload.get('password_token', '').encode()).decode()
    except Exception:
        return None
    return {'email': payload.get('email', ''), 'password': password}


def _strong_temp_password(length=22):
    alphabet = string.ascii_letters + string.digits + '!@#$%*-_+='
    while True:
        value = ''.join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in value)
            and any(c.isupper() for c in value)
            and any(c.isdigit() for c in value)
            and any(c in '!@#$%*-_+=' for c in value)
        ):
            return value


def _valid_academy_owner(academy):
    owner_ids = AcademyMembership.objects.filter(
        academy=academy, role=AcademyMembership.Role.OWNER,
    ).values_list('user_id', flat=True)
    return User.objects.filter(pk__in=owner_ids, is_superuser=False).first()


@platform_owner_required
def system_smtp(request):
    settings_obj = PlatformEmailSettings.load()
    action = request.POST.get('action') if request.method == 'POST' else ''

    if request.method == 'POST' and action == 'disable':
        settings_obj.is_enabled = False
        settings_obj.save(update_fields=['is_enabled', 'updated_at'])
        log_platform_event(request.user, 'smtp_global_deshabilitado')
        messages.warning(request, 'SMTP global deshabilitado. Las academias con SMTP propio seguirán funcionando.')
        return redirect('tenancy:system_smtp')

    form = PlatformSMTPForm(request.POST or None, instance=settings_obj)
    if request.method == 'POST' and action in {'save', 'test'} and form.is_valid():
        settings_obj = form.save()
        log_platform_event(request.user, 'smtp_global_actualizado', metadata={
            'host': settings_obj.smtp_host, 'port': settings_obj.smtp_port, 'usuario': settings_obj.smtp_username,
        })
        if action == 'test':
            recipient = form.cleaned_data['test_email']
            try:
                send_platform_mail(
                    subject='Prueba SMTP · DevLayer Academy',
                    message='El SMTP global de DevLayer Academy está configurado correctamente.',
                    recipients=[recipient],
                    fail_silently=False,
                    html_message=(
                        '<div style="font-family:Arial,sans-serif;color:#172033">'
                        '<h2>DevLayer Academy · SMTP global</h2>'
                        '<p>Si recibiste este mensaje, el proveedor predeterminado está funcionando correctamente.</p>'
                        '</div>'
                    ),
                )
                messages.success(request, f'Configuración guardada y prueba enviada a {recipient}.')
            except Exception as exc:
                messages.error(request, f'La configuración se guardó, pero la prueba falló: {exc}')
        else:
            messages.success(request, 'SMTP global de DevLayer Studio guardado. Las academias que usen el proveedor predeterminado lo heredarán automáticamente.')
        return redirect('tenancy:system_smtp')

    return render(request, 'tenancy/system_smtp.html', {
        'form': form,
        'smtp_settings': settings_obj,
        'smtp_ready': platform_mail_available(),
        'db_smtp_ready': settings_obj.configured,
    })


@platform_owner_required
def academy_create(request):
    if not AcademyPlan.objects.filter(is_active=True).exists():
        messages.warning(request, 'Primero crea al menos un plan activo para poder emitir una licencia.')
        return redirect('tenancy:plan_create')
    form = AcademyCreateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        owner_existed = User.objects.filter(email=form.cleaned_data['owner_email']).exists()
        academy, owner = form.save()
        if not owner_existed:
            _stash_owner_credentials(request, academy, owner, form.cleaned_data['owner_password'])
        log_platform_event(request.user, 'academia_creada', academy, {
            'dueno': owner.email,
            'licencia': academy.license.plan_name,
            'valor': str(academy.license.price),
        })
        if not owner.email_verified:
            try:
                send_verification_email(request, owner, academy)
                messages.success(request, f'Academia “{academy.name}” creada. Enviamos la verificación a {owner.email}.')
            except Exception as exc:
                messages.warning(request, f'Academia creada y dueño asignado, pero el correo de verificación no pudo enviarse: {exc}')
        else:
            messages.success(request, f'Academia “{academy.name}” creada. El dueño {owner.email} ya puede ingresar.')
        return redirect('tenancy:academy_detail', academy.id)
    return render(request, 'tenancy/academy_form.html', {
        'form': form,
        'title': 'Nueva academia y licencia',
        'subtitle': 'Crea el cliente, su licencia y las credenciales del dueño de la academia en una sola operación.',
    })


@platform_owner_required
def academy_detail(request, academy_id):
    academy = get_object_or_404(Academy.objects.select_related('license'), pk=academy_id)
    memberships = list(AcademyMembership.objects.filter(academy=academy).order_by('role', 'created_at'))
    user_map = {str(u.pk): u for u in User.objects.filter(pk__in=[m.user_id for m in memberships], is_superuser=False)}
    user_rows = [{'user': user_map.get(str(m.user_id)), 'membership': m} for m in memberships if user_map.get(str(m.user_id))]
    owner_rows = [row for row in user_rows if row['membership'].role == AcademyMembership.Role.OWNER]
    invalid_owner_ids = AcademyMembership.objects.filter(
        academy=academy, role=AcademyMembership.Role.OWNER,
        user_id__in=User.objects.filter(is_superuser=True).values_list('pk', flat=True),
    ).values_list('user_id', flat=True)
    invalid_owner_accounts = list(User.objects.filter(pk__in=invalid_owner_ids))
    courses = Course.objects.filter(pk__in=academy_course_ids(academy)).order_by('-created_at')[:8]
    academy_form = AcademyEditForm(instance=academy)
    license_form = LicenseForm(instance=academy.current_license)
    owner_credentials = _pop_owner_credentials(request, academy)
    return render(request, 'tenancy/academy_detail.html', {
        'academy': academy,
        'academy_form': academy_form,
        'license_form': license_form,
        'users': user_rows[:20],
        'owners': owner_rows,
        'invalid_owner_accounts': invalid_owner_accounts,
        'owner_credentials': owner_credentials,
        'academy_login_url': reverse('tenancy:academy_login', args=[academy.slug]),
        'courses': courses,
        'usage': academy_license_usage(academy),
        'platform_mail_ready': platform_mail_available(),
    })


@platform_owner_required
def academy_update(request, academy_id):
    academy = get_object_or_404(Academy, pk=academy_id)
    if request.method != 'POST':
        return redirect('tenancy:academy_detail', academy.id)
    form = AcademyEditForm(request.POST, request.FILES, instance=academy)
    if form.is_valid():
        form.save()
        log_platform_event(request.user, 'academia_actualizada', academy)
        messages.success(request, 'Datos de la academia actualizados.')
    else:
        messages.error(request, 'No se pudieron guardar los datos de la academia.')
    return redirect('tenancy:academy_detail', academy.id)


@platform_owner_required
def license_update(request, academy_id):
    academy = get_object_or_404(Academy, pk=academy_id)
    license_obj, _ = AcademyLicense.objects.get_or_create(academy=academy)
    if request.method != 'POST':
        return redirect('tenancy:academy_detail', academy.id)
    form = LicenseForm(request.POST, instance=license_obj)
    if form.is_valid():
        license_obj = form.save()
        log_platform_event(request.user, 'licencia_actualizada', academy, {
            'estado': license_obj.status,
            'valor': str(license_obj.price),
            'cobrado': str(license_obj.amount_paid),
        })
        messages.success(request, 'Licencia y datos financieros actualizados.')
    else:
        messages.error(request, 'Revisa los datos de la licencia.')
    return redirect('tenancy:academy_detail', academy.id)


@platform_owner_required
def license_action(request, academy_id):
    academy = get_object_or_404(Academy, pk=academy_id)
    license_obj, _ = AcademyLicense.objects.get_or_create(academy=academy)
    if request.method != 'POST':
        return redirect('tenancy:academy_detail', academy.id)
    action = request.POST.get('action')
    if action == 'activate':
        license_obj.status = AcademyLicense.Status.ACTIVE
        if license_obj.starts_at and license_obj.starts_at > timezone.localdate():
            license_obj.starts_at = timezone.localdate()
        license_obj.save(update_fields=['status', 'starts_at', 'updated_at'])
        messages.success(request, 'Licencia activada.')
    elif action == 'suspend':
        license_obj.status = AcademyLicense.Status.SUSPENDED
        license_obj.save(update_fields=['status', 'updated_at'])
        messages.warning(request, 'Licencia suspendida. Los usuarios de esa academia no podrán ingresar.')
    elif action == 'cancel':
        license_obj.status = AcademyLicense.Status.CANCELLED
        license_obj.save(update_fields=['status', 'updated_at'])
        messages.warning(request, 'Licencia cancelada.')
    elif action and action.startswith('extend_'):
        days = int(action.split('_', 1)[1])
        license_obj.extend(days)
        messages.success(request, f'Licencia extendida {days} días.')
    log_platform_event(request.user, f'licencia_{action}', academy, {'ends_at': str(license_obj.ends_at or '')})
    return redirect('tenancy:academy_detail', academy.id)


@platform_owner_required
def academy_superadmin_create(request, academy_id):
    """Ruta heredada: ahora crea únicamente el dueño si la academia aún no tiene uno."""
    academy = get_object_or_404(Academy, pk=academy_id)
    current_owner = User.objects.filter(
        pk__in=academy_user_ids(academy, roles=[AcademyMembership.Role.OWNER]),
        is_superuser=False,
    ).first()
    if current_owner:
        messages.info(request, f'Esta academia ya tiene un dueño: {current_owner.email}.')
        return redirect('tenancy:academy_detail', academy.id)

    form = AcademyOwnerForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        existed = User.objects.filter(email=form.cleaned_data['email']).exists()
        user = form.save(academy)
        if not existed:
            _stash_owner_credentials(request, academy, user, form.cleaned_data['password'])
        log_platform_event(request.user, 'dueno_academia_creado', academy, {'email': user.email})
        if not user.email_verified:
            try:
                send_verification_email(request, user, academy)
                messages.success(request, f'Dueño {user.email} creado y correo de verificación enviado.')
            except Exception as exc:
                messages.warning(request, f'Dueño creado, pero no se pudo enviar la verificación: {exc}')
        else:
            messages.success(request, f'Dueño de academia {user.email} creado.')
        return redirect('tenancy:academy_detail', academy.id)
    return render(request, 'tenancy/academy_form.html', {
        'form': form,
        'title': 'Crear dueño de academia',
        'subtitle': academy.name,
    })


@platform_owner_required
def academy_owner_action(request, academy_id):
    academy = get_object_or_404(Academy, pk=academy_id)
    if request.method != 'POST':
        return redirect('tenancy:academy_detail', academy.id)
    owner = _valid_academy_owner(academy)
    if not owner:
        messages.error(request, 'Primero asigna un dueño válido a esta academia.')
        return redirect('tenancy:academy_detail', academy.id)

    action = request.POST.get('action')
    if action == 'resend_verification':
        if owner.email_verified:
            messages.info(request, 'El correo del dueño ya está verificado.')
        else:
            try:
                send_verification_email(request, owner, academy)
                messages.success(request, f'Verificación reenviada a {owner.email}.')
            except Exception as exc:
                messages.error(request, f'No se pudo enviar la verificación: {exc}')
    elif action == 'reset_password':
        password = _strong_temp_password()
        owner.set_password(password)
        owner.save(update_fields=['password', 'updated_at'])
        _stash_owner_credentials(request, academy, owner, password)
        log_platform_event(request.user, 'dueno_password_temporal_generado', academy, {'email': owner.email})
        messages.success(request, 'Nueva contraseña temporal generada. Se mostrará una sola vez en esta pantalla.')
    return redirect('tenancy:academy_detail', academy.id)


def membership_pending(request, slug):
    academy = get_object_or_404(Academy.objects.select_related('license'), slug=slug)
    request.academy = academy
    request.is_academy_public = True
    request.session['academy_slug'] = academy.slug
    membership = None
    if request.user.is_authenticated and not request.user.is_superuser:
        membership = membership_for_user(request.user, academy=academy)
        if membership and membership.status == AcademyMembership.Status.ACTIVE:
            from accounts.views import role_home_url
            return redirect(role_home_url(request.user, academy))
    return render(request, 'accounts/membership_pending.html', {
        'academy': academy,
        'membership': membership,
    })


def license_blocked(request):
    # Esta pantalla solo debe aparecer cuando existe una academia concreta cuya
    # licencia está realmente inactiva. Recuperamos el contexto por varias vías
    # para no confundir una sesión sin tenant con una licencia suspendida.
    academy = getattr(request, 'academy', None) or current_academy_from_session(request)
    requested_slug = (request.GET.get('academia') or '').strip()
    if not academy and requested_slug:
        academy = Academy.objects.select_related('license').filter(slug=requested_slug).first()
    if not academy and request.user.is_authenticated and not request.user.is_superuser:
        academy = academy_for_user(request.user)

    # Si la academia está operativa, esta URL es obsoleta (por ejemplo quedó en
    # el historial del navegador). Autocorregimos el flujo en lugar de mostrar un
    # falso bloqueo.
    if academy and academy.access_enabled:
        request.session['academy_slug'] = academy.slug
        request.session.modified = True
        if request.user.is_authenticated and not request.user.is_superuser:
            membership = membership_for_user(request.user, academy=academy)
            if membership and membership.status == AcademyMembership.Status.ACTIVE:
                from accounts.views import role_home_url
                return redirect(role_home_url(request.user, academy))
        return redirect('tenancy:academy_public', slug=academy.slug)

    reason = 'No se pudo determinar la academia de esta sesión.'
    license_obj = None
    if academy:
        license_obj = academy.current_license
        if not academy.is_active:
            reason = 'La academia está deshabilitada por el administrador de la plataforma.'
        elif not license_obj:
            reason = 'La academia todavía no tiene una licencia asignada.'
        elif license_obj.status == AcademyLicense.Status.SUSPENDED:
            reason = 'La licencia está suspendida temporalmente.'
        elif license_obj.status == AcademyLicense.Status.CANCELLED:
            reason = 'La licencia fue cancelada.'
        elif license_obj.starts_at and timezone.localdate() < license_obj.starts_at:
            reason = f'La licencia empieza el {license_obj.starts_at:%d/%m/%Y}.'
        elif license_obj.ends_at and timezone.localdate() > license_obj.ends_at:
            reason = f'La licencia venció el {license_obj.ends_at:%d/%m/%Y}.'
        else:
            reason = 'La licencia no está disponible temporalmente.'

    return render(request, 'tenancy/license_blocked.html', {
        'academy': academy,
        'license_obj': license_obj,
        'block_reason': reason,
    }, status=403)


PUBLIC_COURSE_STATUSES = [Course.Status.APPROVED, Course.Status.PUBLISHED]


def academy_public_home(request, slug):
    academy = get_object_or_404(Academy.objects.select_related('license'), slug=slug, is_active=True)
    request.academy = academy
    if not academy.access_enabled:
        return render(request, 'tenancy/license_blocked.html', {'academy': academy, 'public_view': True}, status=403)
    request.session['academy_slug'] = academy.slug
    courses = scope_courses(
        Course.objects.filter(status__in=PUBLIC_COURSE_STATUSES).select_related('category').prefetch_related('instructor_links__user', 'modules__lessons'),
        academy,
    )
    categories = scope_categories(Category.objects.filter(is_active=True), academy)
    category_slug = (request.GET.get('categoria') or '').strip()
    if category_slug:
        courses = courses.filter(category__slug=category_slug)
    return render(request, 'tenancy/academy_public.html', {
        'academy': academy,
        'courses': courses,
        'categories': categories,
        'category_filter': category_slug,
    })


def academy_public_course(request, slug, course_slug):
    academy = get_object_or_404(Academy.objects.select_related('license'), slug=slug, is_active=True)
    request.academy = academy
    # Un estudiante autenticado nunca debe caer nuevamente en la experiencia
    # pública de registro/ingreso al abrir un curso desde su panel.
    if request.user.is_authenticated and getattr(request, 'academy_role', '') == AcademyMembership.Role.STUDENT:
        return redirect('catalog:course_detail', slug=course_slug)
    if not academy.access_enabled:
        return render(request, 'tenancy/license_blocked.html', {'academy': academy, 'public_view': True}, status=403)
    request.session['academy_slug'] = academy.slug
    course = get_object_or_404(
        scope_courses(
            Course.objects.select_related('category').prefetch_related('modules__lessons', 'instructor_links__user'),
            academy,
        ),
        slug=course_slug,
        status__in=PUBLIC_COURSE_STATUSES,
    )
    enrollment = None
    latest_order = None
    latest_payment = None
    if request.user.is_authenticated and not request.user.is_superuser:
        enrollment = request.user.enrollments.filter(course=course).first()
        latest_order = Order.objects.filter(user=request.user, course=course).order_by('-created_at').first()
        if latest_order:
            latest_payment = latest_order.payments.order_by('-created_at').first()
    return render(request, 'catalog/course_detail.html', {
        'course': course,
        'enrollment': enrollment,
        'academy': academy,
        'academy_public_url': True,
        'latest_order': latest_order,
        'latest_payment': latest_payment,
    })


def academy_course_thumbnail(request, slug, pk):
    academy = get_object_or_404(Academy.objects.select_related('license'), slug=slug, is_active=True)
    if not academy.access_enabled:
        raise Http404
    course = get_object_or_404(
        scope_courses(Course.objects.all(), academy),
        pk=pk,
        status__in=PUBLIC_COURSE_STATUSES,
    )
    if not course.thumbnail:
        raise Http404
    content_type = mimetypes.guess_type(course.thumbnail.name)[0] or 'image/jpeg'
    response = FileResponse(course.thumbnail.open('rb'), content_type=content_type)
    response['Cache-Control'] = 'public, max-age=3600'
    return response


def academy_logo(request, slug):
    academy = get_object_or_404(Academy, slug=slug)
    if not academy.logo:
        raise Http404
    content_type = mimetypes.guess_type(academy.logo.name)[0] or 'application/octet-stream'
    response = FileResponse(academy.logo.open('rb'), content_type=content_type)
    # El dueño puede reemplazar el logo en cualquier momento. Evitamos que el navegador
    # conserve una versión anterior de /academy/<slug>/logo/.
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response['Pragma'] = 'no-cache'
    return response
