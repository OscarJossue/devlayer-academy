from datetime import timedelta
import mimetypes
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
from billing.models import Order, Payment
from catalog.models import Category, Course
from core.decorators import platform_owner_required

from .forms import AcademyCreateForm, AcademyEditForm, AcademyOwnerForm, AcademyPlanForm, LicenseForm
from .models import Academy, AcademyLicense, AcademyMembership, AcademyPlan, PlatformAuditLog
from .services import academy_course_ids, academy_for_user, academy_license_usage, academy_user_ids, current_academy_from_session, log_platform_event, membership_for_user, scope_categories, scope_courses


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
        owner = User.objects.filter(pk__in=owner_id).first()
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
        owner = User.objects.filter(pk__in=owner_ids).first()
        usage = academy_license_usage(academy)
        rows.append({
            'academy': academy,
            'owner': owner,
            'users': AcademyMembership.objects.filter(academy=academy).count(),
            'courses': academy.course_bindings.count(),
            'usage': usage,
        })
    return render(request, 'tenancy/academy_list.html', {'rows': rows, 'q': q})


@platform_owner_required
def academy_create(request):
    if not AcademyPlan.objects.filter(is_active=True).exists():
        messages.warning(request, 'Primero crea al menos un plan activo para poder emitir una licencia.')
        return redirect('tenancy:plan_create')
    form = AcademyCreateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        academy, owner = form.save()
        log_platform_event(request.user, 'academia_creada', academy, {
            'dueno': owner.email,
            'licencia': academy.license.plan_name,
            'valor': str(academy.license.price),
        })
        messages.success(
            request,
            f'Academia “{academy.name}” creada. El dueño {owner.email} ya puede ingresar y administrar su academia.',
        )
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
    courses = Course.objects.filter(pk__in=academy_course_ids(academy)).order_by('-created_at')[:8]
    academy_form = AcademyEditForm(instance=academy)
    license_form = LicenseForm(instance=academy.current_license)
    return render(request, 'tenancy/academy_detail.html', {
        'academy': academy,
        'academy_form': academy_form,
        'license_form': license_form,
        'users': user_rows[:20],
        'owners': owner_rows,
        'courses': courses,
        'usage': academy_license_usage(academy),
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
    ).first()
    if current_owner:
        messages.info(request, f'Esta academia ya tiene un dueño: {current_owner.email}.')
        return redirect('tenancy:academy_detail', academy.id)

    form = AcademyOwnerForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save(academy)
        log_platform_event(request.user, 'dueno_academia_creado', academy, {'email': user.email})
        messages.success(request, f'Dueño de academia {user.email} creado.')
        return redirect('tenancy:academy_detail', academy.id)
    return render(request, 'tenancy/academy_form.html', {
        'form': form,
        'title': 'Crear dueño de academia',
        'subtitle': academy.name,
    })


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
