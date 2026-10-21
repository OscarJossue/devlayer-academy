from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from core.decorators import verified_email_required
from catalog.models import Course, Lesson
from catalog.pdf_tools import PDFMaterialError, pdf_page_count, render_pdf_page
from tenancy.services import scope_courses
from .models import Enrollment, LessonProgress

from .services import (
    can_access_lesson,
    course_navigation_context,
    mark_lesson_complete,
    next_step_after_lesson,
    previous_lesson_for,
    progress_percentage,
    resume_learning_target,
)


def _lesson_summary_text(lesson):
    # Limpia la copia textual creada por parches antiguos. El material actual se
    # mantiene exclusivamente como PDF optimizado, sin extracción de contenido.
    marker = 'Contenido extraído del material PDF:'
    description = lesson.description or ''
    if marker in description:
        return description.split(marker, 1)[0].strip()
    return description.strip()


def _material_context(course, lesson):
    if not lesson.material_pdf:
        return {'material_page_count': 0, 'material_page_urls': [], 'material_pdf_size': 0}
    try:
        page_count = pdf_page_count(lesson.material_pdf)
        urls = [
            reverse('learning:material_page', kwargs={
                'course_slug': course.slug,
                'lesson_id': lesson.id,
                'page_number': number,
            })
            for number in range(1, page_count + 1)
        ]
        try:
            size = lesson.material_pdf.size
        except (OSError, ValueError):
            size = 0
        return {
            'material_page_count': page_count,
            'material_page_urls': urls,
            'material_pdf_size': size,
        }
    except PDFMaterialError:
        return {'material_page_count': 0, 'material_page_urls': [], 'material_pdf_size': 0}


@verified_email_required
def dashboard(request):
    course_ids = scope_courses(Course.objects.all(), request.academy).values_list('pk', flat=True)
    enrollments = list(
        Enrollment.objects.filter(user=request.user, course_id__in=course_ids)
        .select_related('course', 'course__category')
        .prefetch_related('course__instructor_links__user')
    )
    cards = [{'enrollment': e, 'progress': progress_percentage(e)} for e in enrollments]
    active_count = sum(1 for e in enrollments if e.access_allowed())
    certificate_count = sum(1 for e in enrollments if hasattr(e, 'certificate'))
    average_progress = round(sum(card['progress'] for card in cards) / len(cards)) if cards else 0
    return render(request, 'learning/dashboard.html', {
        'cards': cards,
        'active_count': active_count,
        'certificate_count': certificate_count,
        'average_progress': average_progress,
    })


@verified_email_required
def course_player(request, course_slug):
    course = get_object_or_404(scope_courses(Course.objects.all(), request.academy), slug=course_slug)
    enrollment = get_object_or_404(Enrollment, user=request.user, course=course)
    if not enrollment.access_allowed():
        messages.error(request, 'Tu acceso a este curso no está activo.')
        return redirect('learning:dashboard')
    target = resume_learning_target(enrollment)
    if not target:
        return redirect('learning:completion', course_slug=course.slug)
    if target['kind'] == 'quiz':
        return redirect('assessments:take', quiz_id=target['quiz'].id)
    return redirect('learning:lesson', course_slug=course.slug, lesson_id=target['lesson'].id)


@verified_email_required
def lesson_view(request, course_slug, lesson_id):
    course = get_object_or_404(scope_courses(Course.objects.all(), request.academy), slug=course_slug)
    enrollment = get_object_or_404(Enrollment, user=request.user, course=course)
    lesson = get_object_or_404(
        Lesson.objects.select_related('module', 'module__course'),
        id=lesson_id,
        module__course=course,
    )
    if not can_access_lesson(enrollment, lesson):
        messages.error(request, 'Completa el paso anterior antes de abrir esta clase.')
        return redirect('learning:course_player', course_slug=course.slug)

    progress, created = LessonProgress.objects.get_or_create(enrollment=enrollment, lesson=lesson)
    if not created:
        progress.views_count += 1
        progress.last_viewed_at = timezone.now()
        progress.save(update_fields=['views_count', 'last_viewed_at'])

    context = {
        'course': course,
        'enrollment': enrollment,
        'lesson': lesson,
        'lesson_summary': _lesson_summary_text(lesson),
        'progress': progress,
        'percentage': progress_percentage(enrollment),
        'next_step': next_step_after_lesson(enrollment, lesson),
        'previous_lesson': previous_lesson_for(course, lesson),
    }
    context.update(_material_context(course, lesson))
    context.update(course_navigation_context(enrollment, active_lesson_id=lesson.id))
    return render(request, 'learning/lesson.html', context)


@verified_email_required
def material_page(request, course_slug, lesson_id, page_number):
    """Entrega una sola página renderizada del PDF privado.

    El PDF binario nunca se expone al alumno y no se generan copias permanentes
    por página: el servidor renderiza bajo demanda desde el PDF comprimido.
    """
    course = get_object_or_404(scope_courses(Course.objects.all(), request.academy), slug=course_slug)
    enrollment = get_object_or_404(Enrollment, user=request.user, course=course)
    if not enrollment.access_allowed() and enrollment.status != Enrollment.Status.COMPLETED:
        raise Http404
    lesson = get_object_or_404(
        Lesson.objects.select_related('module', 'module__course'),
        id=lesson_id,
        module__course=course,
    )
    if not lesson.material_pdf or not can_access_lesson(enrollment, lesson):
        raise Http404
    try:
        image = render_pdf_page(lesson.material_pdf, page_number)
    except PDFMaterialError as exc:
        raise Http404 from exc
    response = HttpResponse(image, content_type='image/jpeg')
    response['Content-Disposition'] = 'inline'
    response['Cache-Control'] = 'private, max-age=3600'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@verified_email_required
def complete_lesson(request, course_slug, lesson_id):
    """Marca el paso actual y avanza al siguiente paso real del curso."""
    if request.method != 'POST':
        raise Http404
    course = get_object_or_404(scope_courses(Course.objects.all(), request.academy), slug=course_slug)
    enrollment = get_object_or_404(Enrollment, user=request.user, course=course)
    lesson = get_object_or_404(Lesson.objects.select_related('module'), id=lesson_id, module__course=course)
    if not can_access_lesson(enrollment, lesson):
        raise Http404

    mark_lesson_complete(enrollment, lesson)
    target = next_step_after_lesson(enrollment, lesson)
    if target['kind'] == 'quiz':
        return redirect('assessments:take', quiz_id=target['quiz'].id)
    if target['kind'] == 'lesson':
        return redirect('learning:lesson', course_slug=course.slug, lesson_id=target['lesson'].id)
    return redirect('learning:completion', course_slug=course.slug)


@verified_email_required
def completion(request, course_slug):
    course = get_object_or_404(
        scope_courses(Course.objects.all(), request.academy)
        .prefetch_related('modules__lessons', 'quizzes'),
        slug=course_slug,
    )
    enrollment = get_object_or_404(Enrollment, user=request.user, course=course)
    if not enrollment.access_allowed() and enrollment.status != Enrollment.Status.COMPLETED:
        messages.error(request, 'Tu acceso a este curso no está activo.')
        return redirect('learning:dashboard')

    percentage = progress_percentage(enrollment)
    if percentage < 100:
        messages.info(request, 'Todavía tienes pasos pendientes antes de finalizar el curso.')
        return redirect('learning:course_player', course_slug=course.slug)

    modules = list(course.modules.filter(is_published=True).order_by('order', 'id'))
    attempts = list(
        enrollment.quiz_attempts.select_related('quiz')
        .filter(quiz__course=course, submitted_at__isnull=False)
        .order_by('quiz__kind', 'quiz__created_at', '-submitted_at')
    )
    # Mantener solo el último intento presentado de cada evaluación.
    latest_attempts = []
    seen_quizzes = set()
    for attempt in attempts:
        if attempt.quiz_id in seen_quizzes:
            continue
        seen_quizzes.add(attempt.quiz_id)
        latest_attempts.append(attempt)

    certificate = getattr(enrollment, 'certificate', None)
    return render(request, 'learning/completion.html', {
        'course': course,
        'enrollment': enrollment,
        'percentage': percentage,
        'modules': modules,
        'attempts': latest_attempts,
        'certificate': certificate,
    })


@verified_email_required
def masterclass(request, course_slug):
    course = get_object_or_404(scope_courses(Course.objects.all(), request.academy), slug=course_slug)
    enrollment = get_object_or_404(Enrollment, user=request.user, course=course)
    if not enrollment.access_allowed() and enrollment.status != Enrollment.Status.COMPLETED:
        messages.error(request, 'Tu acceso a este curso no está activo.')
        return redirect('learning:dashboard')
    if not course.masterclass_enabled:
        raise Http404
    context = {
        'course': course,
        'enrollment': enrollment,
    }
    context.update(course_navigation_context(enrollment, active_masterclass=True))
    return render(request, 'learning/masterclass.html', context)


@verified_email_required
def protected_material(request, token):
    # Compatibilidad con enlaces antiguos. El PDF privado nunca se entrega
    # como descarga directa: el visor usa páginas renderizadas autorizadas.
    raise Http404
