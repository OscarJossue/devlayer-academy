import mimetypes

from django.contrib import messages
from django.http import FileResponse, Http404
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect, render
from django.template.defaultfilters import filesizeformat
from django.utils import timezone

from core.decorators import professor_required
from tenancy.services import bind_course, resolve_public_academy, scope_categories, scope_courses
from certificates.design import preview_style_context
from certificates.rendering import render_certificate_pdf
from .forms import CourseContentImportForm, CourseForm, CourseCertificateStyleForm, CourseMasterclassForm, ModuleForm, LessonForm
from .importers import import_course_content_rows, read_content_xlsx
from .models import Category, Course, CourseInstructor, Lesson, Module

PUBLIC_STATUSES = [Course.Status.APPROVED, Course.Status.PUBLISHED]


def _public_courses(request):
    academy = resolve_public_academy(request)
    qs = Course.objects.none()
    categories = Category.objects.none()
    if academy:
        qs = scope_courses(Course.objects.filter(status__in=PUBLIC_STATUSES), academy)
        categories = scope_categories(Category.objects.filter(is_active=True), academy)
    return academy, qs, categories


def course_list(request):
    academy, courses, categories = _public_courses(request)
    if not academy:
        # No existe catálogo global: todo contenido pertenece a un slug de academia.
        return redirect('core:home')
    courses = courses.select_related('category').prefetch_related('instructor_links__user', 'modules__lessons')
    category = request.GET.get('categoria')
    if category:
        courses = courses.filter(category__slug=category)
    return render(request, 'catalog/course_list.html', {'courses': courses, 'categories': categories, 'academy': academy})


def course_thumbnail(request, pk):
    course = get_object_or_404(Course, pk=pk)
    academy = resolve_public_academy(request)
    is_tenant_course = bool(academy and scope_courses(Course.objects.filter(pk=course.pk), academy).exists())
    can_view_unpublished = request.user.is_authenticated and not request.user.is_superuser and is_tenant_course and (
        getattr(request, 'academy_role', '') == 'OWNER' or course.instructor_links.filter(user=request.user).exists()
    )
    if not is_tenant_course or (course.status not in PUBLIC_STATUSES and not can_view_unpublished):
        raise Http404
    if not course.thumbnail:
        raise Http404
    content_type = mimetypes.guess_type(course.thumbnail.name)[0] or 'image/jpeg'
    response = FileResponse(course.thumbnail.open('rb'), content_type=content_type)
    response['Cache-Control'] = 'public, max-age=3600' if course.status in PUBLIC_STATUSES else 'private, no-store'
    return response


def course_detail(request, slug):
    academy = resolve_public_academy(request)
    if not academy:
        return redirect('catalog:course_list')
    qs = scope_courses(Course.objects.select_related('category').prefetch_related('modules__lessons'), academy)
    course = get_object_or_404(qs, slug=slug)
    can_manage = request.user.is_authenticated and not request.user.is_superuser and (
        getattr(request, 'academy_role', '') == 'OWNER' or course.instructor_links.filter(user=request.user).exists()
    )
    if course.status not in PUBLIC_STATUSES and not can_manage:
        return redirect('catalog:course_list')
    enrollment = request.user.enrollments.filter(course=course).first() if request.user.is_authenticated and not request.user.is_superuser else None
    latest_order = None
    latest_payment = None
    if request.user.is_authenticated and not request.user.is_superuser:
        # El estado de compra se muestra en la ficha del curso para que el estudiante
        # sepa si su comprobante está esperando revisión o si debe corregirlo.
        from billing.models import Order
        latest_order = (
            Order.objects.filter(user=request.user, course=course)
            .prefetch_related('payments')
            .order_by('-created_at')
            .first()
        )
        if latest_order:
            latest_payment = latest_order.payments.order_by('-created_at').first()
    return render(request, 'catalog/course_detail.html', {
        'course': course,
        'enrollment': enrollment,
        'academy': academy,
        'latest_order': latest_order,
        'latest_payment': latest_payment,
    })


def _academy_courses_for_professor(request):
    qs = scope_courses(Course.objects.all(), request.academy)
    if getattr(request, 'academy_role', '') != 'OWNER':
        qs = qs.filter(instructor_links__user=request.user)
    return qs.distinct()


@professor_required
def professor_dashboard(request):
    courses = _academy_courses_for_professor(request).select_related('category').prefetch_related('modules', 'quizzes')
    stats = {'total': courses.count(), 'published': courses.filter(status__in=PUBLIC_STATUSES).count(), 'review': courses.filter(status=Course.Status.REVIEW).count(), 'students': sum(course.enrollments.count() for course in courses)}
    return render(request, 'professor/dashboard.html', {'courses': courses, 'stats': stats, 'academy': request.academy})


@professor_required
def course_create(request):
    form = CourseForm(request.POST or None, request.FILES or None, academy=request.academy)
    if request.method == 'POST' and form.is_valid():
        course = form.save(commit=False); course.created_by = request.user; course.status = Course.Status.DRAFT; course.save(); bind_course(course, request.academy)
        CourseInstructor.objects.get_or_create(course=course, user=request.user, defaults={'is_owner': True})
        messages.success(request, 'Curso creado como borrador. Ahora agrega módulos, clases y evaluaciones.')
        return redirect('catalog:professor_course_edit', course.pk)
    return render(request, 'professor/course_form.html', {'form': form, 'title': 'Crear curso'})


def _professor_course(request, pk):
    qs = scope_courses(Course.objects.all(), request.academy)
    if getattr(request, 'academy_role', '') != 'OWNER':
        qs = qs.filter(instructor_links__user=request.user)
    return get_object_or_404(qs.distinct(), pk=pk)


@professor_required
def course_edit(request, pk):
    course = _professor_course(request, pk)
    section = request.POST.get('section') if request.method == 'POST' else ''

    # Cada bloque se guarda de forma independiente para mantener la interfaz rápida.
    form = CourseForm(instance=course, academy=request.academy)
    form.fields.pop('certificate_enabled', None)
    form.fields.pop('certificate_style_mode', None)
    certificate_form = CourseCertificateStyleForm(instance=course, academy=request.academy, prefix='certificate')
    masterclass_form = CourseMasterclassForm(instance=course, prefix='masterclass')

    if request.method == 'POST' and section == 'certificate':
        certificate_form = CourseCertificateStyleForm(
            request.POST, request.FILES, instance=course, academy=request.academy, prefix='certificate'
        )
        if certificate_form.is_valid():
            obj = certificate_form.save(commit=False)
            if obj.status in PUBLIC_STATUSES:
                obj.status = Course.Status.REVIEW
            obj.save()
            messages.success(request, 'Configuración del certificado guardada. Si el curso estaba publicado, volvió a revisión.')
            return redirect('catalog:professor_course_edit', course.pk)

    elif request.method == 'POST' and section == 'masterclass':
        masterclass_form = CourseMasterclassForm(request.POST, instance=course, prefix='masterclass')
        if masterclass_form.is_valid():
            masterclass_form.save()
            messages.success(request, 'Clase magistral actualizada. El cambio se refleja inmediatamente para los estudiantes.')
            return redirect('catalog:professor_course_edit', course.pk)

    elif request.method == 'POST':
        form = CourseForm(request.POST, request.FILES, instance=course, academy=request.academy)
        form.fields.pop('certificate_enabled', None)
        form.fields.pop('certificate_style_mode', None)
        if form.is_valid():
            obj = form.save(commit=False)
            if obj.status in PUBLIC_STATUSES:
                obj.status = Course.Status.REVIEW
            obj.save()
            messages.success(request, 'Curso actualizado. Los cambios importantes deben revisarse antes de volver a publicarse.')
            return redirect('catalog:professor_course_edit', course.pk)

    return render(request, 'professor/course_edit.html', {
        'form': form,
        'certificate_form': certificate_form,
        'masterclass_form': masterclass_form,
        'course': course,
        'certificate_preview': preview_style_context(course, request.academy),
    })


@professor_required
def certificate_preview(request, pk):
    course = _professor_course(request, pk)
    if not course.certificate_enabled:
        messages.info(request, 'Este curso no tiene certificados habilitados.')
        return redirect('catalog:professor_course_edit', course.pk)
    buf = render_certificate_pdf(
        request.academy, course, 'Nombre del estudiante', code='VISTA-PREVIA', issued_at=timezone.now()
    )
    return FileResponse(buf, content_type='application/pdf', as_attachment=False, filename='vista-previa-certificado.pdf')


@professor_required
def submit_review(request, pk):
    course = _professor_course(request, pk)
    if request.method == 'POST': course.status = Course.Status.REVIEW; course.save(update_fields=['status', 'updated_at']); messages.success(request, 'Curso enviado a revisión del dueño de la academia.')
    return redirect('catalog:professor_course_edit', course.pk)


@professor_required
def module_create(request, course_pk):
    course = _professor_course(request, course_pk)
    form = ModuleForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        module = form.save(commit=False)
        module.course = course
        module.order = (course.modules.aggregate(value=Max('order'))['value'] or 0) + 1
        module.save()
        messages.success(request, 'Módulo agregado. Ya puedes cargar la primera clase.')
        return redirect('catalog:professor_course_edit', course.pk)
    return render(request, 'professor/simple_form.html', {
        'form': form,
        'title': f'Nuevo módulo · {course.title}',
        'helper': 'Solo define el nombre y un resumen. Academy coloca el módulo automáticamente al final del curso.',
        'back_url': course.id,
    })


@professor_required
def lesson_create(request, module_pk):
    module = get_object_or_404(Module.objects.select_related('course'), pk=module_pk)
    _professor_course(request, module.course_id)
    form = LessonForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        lesson = form.save(commit=False)
        lesson.module = module
        lesson.order = (module.lessons.aggregate(value=Max('order'))['value'] or 0) + 1
        lesson.video_provider = Lesson.VideoProvider.YOUTUBE if lesson.video_source else Lesson.VideoProvider.NONE
        lesson.is_preview = False
        lesson.is_published = True
        lesson.save()
        info = getattr(form, 'pdf_optimization_info', None)
        if info:
            before = filesizeformat(info['original_size'])
            after = filesizeformat(info['optimized_size'])
            messages.success(
                request,
                f'Clase cargada. PDF optimizado automáticamente: {before} → {after} · {info["pages"]} página(s).',
            )
        else:
            messages.success(request, 'Clase cargada. El contenido quedó listo dentro del módulo.')
        return redirect('catalog:professor_course_edit', module.course_id)
    return render(request, 'professor/simple_form.html', {
        'form': form,
        'title': f'Carga rápida · {module.title}',
        'helper': 'Carga título, video y PDF. Academy comprime el PDF automáticamente sin convertirlo a texto, calcula el orden y deja el resto con valores recomendados.',
        'back_url': module.course_id,
    })


@professor_required
def import_content(request, pk):
    course = _professor_course(request, pk); session_key = f'preview_contenido_{course.id}'; preview_rows = request.session.get(session_key, []); preview_errors = []; form = CourseContentImportForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and request.POST.get('action') == 'confirm':
        if not preview_rows: messages.error(request, 'No hay una previsualización pendiente.'); return redirect('catalog:professor_import_content', course.id)
        result = import_course_content_rows(course, preview_rows); request.session.pop(session_key, None); messages.success(request, f"Contenido importado: {result['modules_created']} módulos, {result['lessons_created']} clases nuevas y {result['lessons_updated']} actualizadas.")
        for error in result['errors'][:12]: messages.warning(request, error)
        return redirect('catalog:professor_course_edit', course.id)
    if request.method == 'POST' and form.is_valid():
        try: preview_rows, preview_errors = read_content_xlsx(form.cleaned_data['xlsx_file'])
        except ValueError as exc: messages.error(request, str(exc)); preview_rows = []
        else: request.session[session_key] = preview_rows; request.session.modified = True
    return render(request, 'professor/import_content.html', {'form': form, 'course': course, 'preview_rows': preview_rows, 'preview_errors': preview_errors})


@professor_required
def professor_students(request, pk):
    from learning.services import progress_percentage
    course = _professor_course(request, pk)
    enrollments = course.enrollments.select_related('user').all()
    rows = []
    for enrollment in enrollments:
        attempts = list(
            enrollment.quiz_attempts.select_related('quiz')
            .filter(quiz__course=course, submitted_at__isnull=False)
            .order_by('-submitted_at')
        )
        rows.append({'enrollment': enrollment, 'progress': progress_percentage(enrollment), 'attempts': attempts})
    return render(request, 'professor/students.html', {'course': course, 'rows': rows})
