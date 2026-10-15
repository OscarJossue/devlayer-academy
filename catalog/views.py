import mimetypes

from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

from core.decorators import professor_required
from .forms import CourseContentImportForm, CourseForm, ModuleForm, LessonForm
from .importers import import_course_content_rows, read_content_xlsx
from .models import Category, Course, CourseInstructor, Module

PUBLIC_STATUSES = [Course.Status.APPROVED, Course.Status.PUBLISHED]


def course_list(request):
    courses = Course.objects.filter(status__in=PUBLIC_STATUSES).select_related('category').prefetch_related('instructor_links__user')
    category = request.GET.get('categoria')
    if category:
        courses = courses.filter(category__slug=category)
    return render(request, 'catalog/course_list.html', {'courses': courses, 'categories': Category.objects.filter(is_active=True)})


def course_thumbnail(request, pk):
    course = get_object_or_404(Course, pk=pk)
    can_view_unpublished = request.user.is_authenticated and (
        request.user.is_superuser or getattr(request.user, 'role', '') == 'SUPERADMIN' or course.instructor_links.filter(user=request.user).exists()
    )
    if course.status not in PUBLIC_STATUSES and not can_view_unpublished:
        raise Http404
    if not course.thumbnail:
        raise Http404
    content_type = mimetypes.guess_type(course.thumbnail.name)[0] or 'image/jpeg'
    response = FileResponse(course.thumbnail.open('rb'), content_type=content_type)
    response['Cache-Control'] = 'public, max-age=3600' if course.status in PUBLIC_STATUSES else 'private, no-store'
    return response


def course_detail(request, slug):
    course = get_object_or_404(Course.objects.select_related('category').prefetch_related('modules__lessons'), slug=slug)
    if course.status not in PUBLIC_STATUSES and not (
        request.user.is_authenticated and (request.user.is_superuser or getattr(request.user, 'role', '') == 'SUPERADMIN' or course.instructor_links.filter(user=request.user).exists())
    ):
        return redirect('catalog:course_list')
    enrollment = request.user.enrollments.filter(course=course).first() if request.user.is_authenticated else None
    return render(request, 'catalog/course_detail.html', {'course': course, 'enrollment': enrollment})


@professor_required
def professor_dashboard(request):
    qs = Course.objects.all() if request.user.is_superuser else Course.objects.filter(instructor_links__user=request.user)
    courses = qs.distinct().select_related('category').prefetch_related('modules', 'quizzes')
    stats = {
        'total': courses.count(),
        'published': courses.filter(status__in=PUBLIC_STATUSES).count(),
        'review': courses.filter(status=Course.Status.REVIEW).count(),
        'students': sum(course.enrollments.count() for course in courses),
    }
    return render(request, 'professor/dashboard.html', {'courses': courses, 'stats': stats})


@professor_required
def course_create(request):
    form = CourseForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        course = form.save(commit=False)
        course.created_by = request.user
        course.status = Course.Status.DRAFT
        course.save()
        CourseInstructor.objects.get_or_create(course=course, user=request.user, defaults={'is_owner': True})
        messages.success(request, 'Curso creado como borrador. Ahora agrega módulos, clases y evaluaciones.')
        return redirect('catalog:professor_course_edit', course.pk)
    return render(request, 'professor/course_form.html', {'form': form, 'title': 'Crear curso'})


def _professor_course(user, pk):
    qs = Course.objects.all()
    if not user.is_superuser:
        qs = qs.filter(instructor_links__user=user)
    return get_object_or_404(qs.distinct(), pk=pk)


@professor_required
def course_edit(request, pk):
    course = _professor_course(request.user, pk)
    form = CourseForm(request.POST or None, request.FILES or None, instance=course)
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        if obj.status in PUBLIC_STATUSES:
            obj.status = Course.Status.REVIEW
        obj.save()
        messages.success(request, 'Curso actualizado. Los cambios importantes deben ser revisados antes de volver a publicarse.')
        return redirect('catalog:professor_course_edit', course.pk)
    return render(request, 'professor/course_edit.html', {'form': form, 'course': course})


@professor_required
def submit_review(request, pk):
    course = _professor_course(request.user, pk)
    if request.method == 'POST':
        course.status = Course.Status.REVIEW
        course.save(update_fields=['status', 'updated_at'])
        messages.success(request, 'Curso enviado a revisión del superadministrador.')
    return redirect('catalog:professor_course_edit', course.pk)


@professor_required
def module_create(request, course_pk):
    course = _professor_course(request.user, course_pk)
    form = ModuleForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        module = form.save(commit=False)
        module.course = course
        module.save()
        messages.success(request, 'Módulo agregado correctamente.')
        return redirect('catalog:professor_course_edit', course.pk)
    return render(request, 'professor/simple_form.html', {
        'form': form,
        'title': f'Nuevo módulo · {course.title}',
        'helper': 'Define el orden del módulo y si el estudiante debe aprobar su cuestionario antes de continuar.',
        'back_url': course.id,
    })


@professor_required
def lesson_create(request, module_pk):
    module = get_object_or_404(Module.objects.select_related('course'), pk=module_pk)
    _professor_course(request.user, module.course_id)
    form = LessonForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        lesson = form.save(commit=False)
        lesson.module = module
        lesson.save()
        messages.success(request, 'Clase agregada correctamente.')
        return redirect('catalog:professor_course_edit', module.course_id)
    return render(request, 'professor/simple_form.html', {
        'form': form,
        'title': f'Nueva clase · {module.title}',
        'helper': 'Agrega video, descripción y PDF. La URL del video se guarda cifrada y el PDF se sirve con acceso protegido.',
        'back_url': module.course_id,
    })


@professor_required
def import_content(request, pk):
    course = _professor_course(request.user, pk)
    session_key = f'preview_contenido_{course.id}'
    preview_rows = request.session.get(session_key, [])
    preview_errors = []
    form = CourseContentImportForm(request.POST or None, request.FILES or None)

    if request.method == 'POST' and request.POST.get('action') == 'confirm':
        if not preview_rows:
            messages.error(request, 'No hay una previsualización pendiente. Vuelve a cargar el XLSX.')
            return redirect('catalog:professor_import_content', course.id)
        result = import_course_content_rows(course, preview_rows)
        request.session.pop(session_key, None)
        messages.success(request, f"Contenido importado: {result['modules_created']} módulos nuevos, {result['lessons_created']} clases nuevas y {result['lessons_updated']} actualizadas.")
        for error in result['errors'][:12]:
            messages.warning(request, error)
        return redirect('catalog:professor_course_edit', course.id)

    if request.method == 'POST' and form.is_valid():
        try:
            preview_rows, preview_errors = read_content_xlsx(form.cleaned_data['xlsx_file'])
        except ValueError as exc:
            messages.error(request, str(exc))
            preview_rows = []
        else:
            request.session[session_key] = preview_rows
            request.session.modified = True

    return render(request, 'professor/import_content.html', {
        'form': form,
        'course': course,
        'preview_rows': preview_rows,
        'preview_errors': preview_errors,
    })


@professor_required
def professor_students(request, pk):
    from learning.services import progress_percentage
    course = _professor_course(request.user, pk)
    enrollments = course.enrollments.select_related('user').all()
    rows = []
    for enrollment in enrollments:
        attempts = list(enrollment.quiz_attempts.select_related('quiz').filter(quiz__course=course, submitted_at__isnull=False))
        from assessments.services import attempt_needs_review
        for attempt in attempts:
            attempt.pending_manual_review = attempt_needs_review(attempt)
        rows.append({'enrollment': enrollment, 'progress': progress_percentage(enrollment), 'attempts': attempts})
    return render(request, 'professor/students.html', {'course': course, 'rows': rows})
