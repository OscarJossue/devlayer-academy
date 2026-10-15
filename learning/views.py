from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from core.decorators import verified_email_required
from catalog.models import Course, Lesson
from .models import Enrollment, LessonProgress
from .services import can_access_lesson, mark_lesson_complete, progress_percentage

@login_required
def dashboard(request):
    enrollments = list(Enrollment.objects.filter(user=request.user).select_related('course', 'course__category').prefetch_related('course__instructor_links__user'))
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
    course = get_object_or_404(Course, slug=course_slug)
    enrollment = get_object_or_404(Enrollment, user=request.user, course=course)
    if not enrollment.access_allowed():
        messages.error(request, 'Tu acceso a este curso no está activo.')
        return redirect('learning:dashboard')
    lessons = Lesson.objects.filter(module__course=course, is_published=True).select_related('module')
    first = next((lesson for lesson in lessons if can_access_lesson(enrollment, lesson)), None)
    if not first:
        messages.warning(request, 'No hay clases disponibles todavía.')
        return redirect('learning:dashboard')
    return redirect('learning:lesson', course_slug=course.slug, lesson_id=first.id)

@verified_email_required
def lesson_view(request, course_slug, lesson_id):
    course = get_object_or_404(Course, slug=course_slug)
    enrollment = get_object_or_404(Enrollment, user=request.user, course=course)
    lesson = get_object_or_404(Lesson.objects.select_related('module', 'module__course'), id=lesson_id, module__course=course)
    if not can_access_lesson(enrollment, lesson):
        messages.error(request, 'Completa el contenido anterior antes de abrir esta clase.')
        return redirect('learning:course_player', course_slug=course.slug)
    progress, created = LessonProgress.objects.get_or_create(enrollment=enrollment, lesson=lesson)
    if not created:
        progress.views_count += 1
        progress.last_viewed_at = timezone.now()
        progress.save(update_fields=['views_count', 'last_viewed_at'])
    lessons = list(Lesson.objects.filter(module__course=course, is_published=True).select_related('module'))
    material_url = None
    if lesson.material_pdf:
        token = signing.dumps({'lesson': str(lesson.id), 'user': str(request.user.id)}, salt='material-access')
        material_url = reverse('learning:material', args=[token])
    return render(request, 'learning/lesson.html', {
        'course': course, 'enrollment': enrollment, 'lesson': lesson, 'progress': progress,
        'lessons': lessons, 'material_url': material_url, 'percentage': progress_percentage(enrollment),
    })

@verified_email_required
def complete_lesson(request, course_slug, lesson_id):
    if request.method != 'POST':
        raise Http404
    course = get_object_or_404(Course, slug=course_slug)
    enrollment = get_object_or_404(Enrollment, user=request.user, course=course)
    lesson = get_object_or_404(Lesson, id=lesson_id, module__course=course)
    if not can_access_lesson(enrollment, lesson):
        raise Http404
    mark_lesson_complete(enrollment, lesson)
    messages.success(request, 'Clase completada.')
    return redirect('learning:lesson', course_slug=course.slug, lesson_id=lesson.id)

@verified_email_required
def protected_material(request, token):
    try:
        data = signing.loads(token, salt='material-access', max_age=60 * 10)
    except signing.BadSignature:
        raise Http404
    if data.get('user') != str(request.user.id):
        raise Http404
    lesson = get_object_or_404(Lesson.objects.select_related('module__course'), id=data.get('lesson'))
    enrollment = get_object_or_404(Enrollment, user=request.user, course=lesson.module.course)
    if not enrollment.access_allowed() or not lesson.material_pdf:
        raise Http404
    response = FileResponse(lesson.material_pdf.open('rb'), content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="material-{lesson.id}.pdf"'
    response['Cache-Control'] = 'private, no-store, max-age=0'
    response['Pragma'] = 'no-cache'
    return response
