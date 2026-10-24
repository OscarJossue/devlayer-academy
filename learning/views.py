from io import BytesIO

from django.contrib import messages
from django.core import signing
from django.http import Http404, HttpResponse
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from PIL import Image, ImageDraw, ImageFont
from core.decorators import verified_email_required
from catalog.models import Course, Lesson
from catalog.pdf_tools import PDFMaterialError, pdf_page_count, render_pdf_page
from tenancy.models import AcademyMembership
from tenancy.services import scope_courses
from .models import Enrollment, LessonProgress
from assessments.models import Quiz, QuizAttempt
from assessments.services import attempt_timing, valid_quizzes_for_course

SECURE_VIDEO_SALT = 'learning.secure-video.v1'
SECURE_VIDEO_MAX_AGE = 60 * 20


from .services import (
    can_access_lesson,
    course_navigation_context,
    mark_lesson_complete,
    next_step_after_lesson,
    previous_lesson_for,
    progress_percentage,
    resume_learning_target,
)


def _watermark_material_page(image_bytes, text):
    """Incrusta una marca de sesión en la imagen renderizada del PDF."""
    try:
        source = Image.open(BytesIO(image_bytes)).convert('RGB')
        overlay = Image.new('RGBA', source.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)
        try:
            font = ImageFont.load_default(size=max(18, source.width // 95))
        except TypeError:
            font = ImageFont.load_default()
        safe_text = (text or 'DEVLAYER ACADEMY').strip()[:160]
        step_x = max(360, source.width // 3)
        step_y = max(240, source.height // 4)
        for row, y in enumerate(range(70, source.height, step_y)):
            offset = 50 if row % 2 == 0 else step_x // 2
            for x in range(offset, source.width, step_x):
                draw.text((x, y), safe_text, font=font, fill=(20, 29, 50, 45))
        merged = Image.alpha_composite(source.convert('RGBA'), overlay).convert('RGB')
        output = BytesIO()
        merged.save(output, format='JPEG', quality=88, optimize=True, progressive=True)
        return output.getvalue()
    except Exception:
        # La visualización nunca debe fallar solo por la marca de agua.
        return image_bytes


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


def _student_enrollment_cards(request):
    course_ids = scope_courses(Course.objects.all(), request.academy).values_list('pk', flat=True)
    enrollments = list(
        Enrollment.objects.filter(user=request.user, course_id__in=course_ids)
        .select_related('course', 'course__category')
        .prefetch_related('course__instructor_links__user')
        .order_by('-updated_at')
    )
    return [{'enrollment': enrollment, 'progress': progress_percentage(enrollment)} for enrollment in enrollments]


def _student_activity_stats(request, cards):
    enrollments = [card['enrollment'] for card in cards]
    enrollment_ids = [item.id for item in enrollments]
    activity_datetimes = []

    if enrollment_ids:
        activity_datetimes.extend(
            value for value in LessonProgress.objects.filter(
                enrollment_id__in=enrollment_ids,
            ).values_list('last_viewed_at', flat=True) if value
        )
        activity_datetimes.extend(
            value for value in QuizAttempt.objects.filter(
                enrollment_id__in=enrollment_ids, submitted_at__isnull=False,
            ).values_list('submitted_at', flat=True) if value
        )

    active_days = len({timezone.localdate(value) for value in activity_datetimes})
    last_study_activity = max(activity_datetimes) if activity_datetimes else None
    membership = getattr(request, 'academy_membership', None)
    baseline = (
        last_study_activity
        or getattr(membership, 'created_at', None)
        or request.user.date_joined
    )
    days_without_study = max((timezone.localdate() - timezone.localdate(baseline)).days, 0) if baseline else 0

    completed_count = sum(
        1 for card in cards
        if card['enrollment'].status == Enrollment.Status.COMPLETED or card['progress'] >= 100
    )
    active_count = sum(
        1 for card in cards
        if card['enrollment'].access_allowed() and card['progress'] < 100
    )
    certificate_count = sum(1 for card in cards if hasattr(card['enrollment'], 'certificate'))
    average_progress = round(sum(card['progress'] for card in cards) / len(cards)) if cards else 0

    return {
        'active_count': active_count,
        'completed_count': completed_count,
        'certificate_count': certificate_count,
        'average_progress': average_progress,
        'active_days': active_days,
        'days_without_study': days_without_study,
        'last_study_activity': last_study_activity,
        'last_login': request.user.last_login,
    }


@verified_email_required
def dashboard(request):
    cards = _student_enrollment_cards(request)
    stats = _student_activity_stats(request, cards)
    continue_cards = [card for card in cards if card['enrollment'].access_allowed() and card['progress'] < 100][:3]
    return render(request, 'learning/dashboard.html', {
        'stats': stats,
        'continue_cards': continue_cards,
    })


@verified_email_required
def my_courses(request):
    cards = _student_enrollment_cards(request)
    return render(request, 'learning/my_courses.html', {
        'cards': cards,
        'stats': _student_activity_stats(request, cards),
    })


def _academic_quiz_rows(enrollment):
    # El récord usa la misma relación académica que el reproductor y los
    # certificados. Nunca incorpora cuestionarios de otro curso o módulo.
    quizzes = list(
        valid_quizzes_for_course(enrollment.course)
        .filter(
            Q(is_active=True)
            | Q(attempts__enrollment=enrollment, attempts__submitted_at__isnull=False)
        )
        .select_related('module')
        .distinct()
        .order_by('module__order', 'kind', 'created_at', 'id')
    )
    rows = []
    for quiz in quizzes:
        attempts = list(
            QuizAttempt.objects.filter(
                enrollment=enrollment,
                quiz=quiz,
                submitted_at__isnull=False,
            ).order_by('number')
        )
        scored = [attempt for attempt in attempts if attempt.score is not None]
        best = max(scored, key=lambda item: item.score) if scored else None
        latest = scored[-1] if scored else None
        latest_timing = attempt_timing(latest) if latest else None
        rows.append({
            'quiz': quiz,
            'area': quiz.module.title if quiz.module_id else 'Examen final',
            'attempts': len(attempts),
            'best_score': float(best.score) if best else None,
            'best_score_display': f'{float(best.score):.1f}%' if best else '—',
            'latest_score': float(latest.score) if latest else None,
            'latest_score_display': f'{float(latest.score):.1f}%' if latest else '—',
            'passed': any(attempt.passed for attempt in attempts),
            'required_score': quiz.required_score,
            'timing_label': quiz.timing_label,
            'latest_duration_display': latest_timing['elapsed_label'] if latest_timing else '—',
            'latest_overtime_display': latest_timing['overtime_label'] if latest_timing and latest_timing['overtime_seconds'] else '',
        })
    return rows


def _academic_course_card(enrollment):
    quiz_rows = _academic_quiz_rows(enrollment)
    graded = [row['best_score'] for row in quiz_rows if row['best_score'] is not None]
    academic_average = round(sum(graded) / len(graded), 1) if graded else None
    final_rows = [row for row in quiz_rows if row['quiz'].kind == Quiz.Kind.FINAL]
    final_graded = [row['best_score'] for row in final_rows if row['best_score'] is not None]
    closing_score = round(max(final_graded), 1) if final_graded else academic_average
    required_rows = [row for row in quiz_rows if row['quiz'].is_required]
    required_passed = sum(1 for row in required_rows if row['passed'])
    progress = progress_percentage(enrollment)
    completed = enrollment.status == Enrollment.Status.COMPLETED or progress >= 100
    course_passed = completed and all(row['passed'] for row in required_rows)
    if completed and course_passed:
        status_label = 'Aprobado'
        status_class = 'is-passed'
    elif completed:
        status_label = 'Finalizado'
        status_class = 'is-finished'
    else:
        status_label = 'En progreso'
        status_class = 'is-progress'
    return {
        'enrollment': enrollment,
        'progress': progress,
        'academic_average': academic_average,
        'academic_average_display': f'{academic_average:.1f}%' if academic_average is not None else '—',
        'closing_score': closing_score,
        'closing_score_display': f'{closing_score:.1f}%' if closing_score is not None else '—',
        'quiz_rows': quiz_rows,
        'quiz_total': len(quiz_rows),
        'quiz_attempted': sum(1 for row in quiz_rows if row['attempts']),
        'quiz_passed': sum(1 for row in quiz_rows if row['passed']),
        'required_total': len(required_rows),
        'required_passed': required_passed,
        'course_passed': course_passed,
        'completed': completed,
        'status_label': status_label,
        'status_class': status_class,
        'has_certificate': hasattr(enrollment, 'certificate'),
    }


def _student_academic_cards(request):
    course_ids = scope_courses(Course.objects.all(), request.academy).values_list('pk', flat=True)
    enrollments = list(
        Enrollment.objects.filter(user=request.user, course_id__in=course_ids)
        .select_related('course', 'course__category')
        .order_by('-updated_at')
    )
    return [_academic_course_card(enrollment) for enrollment in enrollments]


@verified_email_required
def academic_record(request):
    if getattr(request, 'academy_role', None) != AcademyMembership.Role.STUDENT:
        raise Http404
    cards = _student_academic_cards(request)
    averages = [card['academic_average'] for card in cards if card['academic_average'] is not None]
    assessed_courses = len(averages)
    total_assessments = sum(card['quiz_attempted'] for card in cards)
    passed_assessments = sum(card['quiz_passed'] for card in cards)
    stats = {
        'courses_total': len(cards),
        'courses_completed': sum(1 for card in cards if card['completed']),
        'courses_passed': sum(1 for card in cards if card['course_passed']),
        'academic_average': round(sum(averages) / assessed_courses, 1) if averages else None,
        'academic_average_display': f'{(sum(averages) / assessed_courses):.1f}%' if averages else '—',
        'assessments_total': total_assessments,
        'assessments_passed': passed_assessments,
        'assessment_success': round((passed_assessments / total_assessments) * 100) if total_assessments else 0,
    }
    return render(request, 'learning/academic_record.html', {'cards': cards, 'stats': stats})


@verified_email_required
def academic_record_course(request, course_slug):
    if getattr(request, 'academy_role', None) != AcademyMembership.Role.STUDENT:
        raise Http404
    course = get_object_or_404(scope_courses(Course.objects.all(), request.academy), slug=course_slug)
    enrollment = get_object_or_404(Enrollment.objects.select_related('course', 'course__category'), user=request.user, course=course)
    card = _academic_course_card(enrollment)
    return render(request, 'learning/academic_record_course.html', {
        'course': course,
        'card': card,
    })


@verified_email_required
def course_player(request, course_slug):
    course = get_object_or_404(scope_courses(Course.objects.all(), request.academy), slug=course_slug)
    enrollment = get_object_or_404(Enrollment, user=request.user, course=course)
    if not enrollment.access_allowed():
        messages.error(request, 'Tu acceso a este curso no está activo.')
        return redirect('learning:my_courses')
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

    video_frame_url = ''
    if lesson.youtube_id():
        video_token = signing.dumps({
            'lesson_id': str(lesson.id),
            'course_id': str(course.id),
            'user_id': str(request.user.id),
            'academy_id': str(request.academy.id),
        }, salt=SECURE_VIDEO_SALT, compress=True)
        video_frame_url = reverse('learning:secure_video_frame', kwargs={
            'course_slug': course.slug,
            'lesson_id': lesson.id,
            'token': video_token,
        })

    context = {
        'course': course,
        'enrollment': enrollment,
        'lesson': lesson,
        'lesson_summary': _lesson_summary_text(lesson),
        'progress': progress,
        'percentage': progress_percentage(enrollment),
        'next_step': next_step_after_lesson(enrollment, lesson),
        'previous_lesson': previous_lesson_for(course, lesson),
        'video_frame_url': video_frame_url,
    }
    context.update(_material_context(course, lesson))
    context.update(course_navigation_context(enrollment, active_lesson_id=lesson.id))
    return render(request, 'learning/lesson.html', context)


@xframe_options_sameorigin
@verified_email_required
def secure_video_frame(request, course_slug, lesson_id, token):
    """Reproductor intermedio autenticado para videos de YouTube.

    La página principal nunca recibe la URL original almacenada. El token es
    firmado, expira y está ligado a academia, usuario, curso y clase.
    """
    try:
        payload = signing.loads(token, salt=SECURE_VIDEO_SALT, max_age=SECURE_VIDEO_MAX_AGE)
    except signing.BadSignature as exc:
        raise Http404 from exc

    course = get_object_or_404(scope_courses(Course.objects.all(), request.academy), slug=course_slug)
    enrollment = get_object_or_404(Enrollment, user=request.user, course=course)
    lesson = get_object_or_404(
        Lesson.objects.select_related('module', 'module__course'),
        id=lesson_id,
        module__course=course,
    )
    expected = {
        'lesson_id': str(lesson.id),
        'course_id': str(course.id),
        'user_id': str(request.user.id),
        'academy_id': str(request.academy.id),
    }
    if any(str(payload.get(key, '')) != value for key, value in expected.items()):
        raise Http404
    if not enrollment.access_allowed() and enrollment.status != Enrollment.Status.COMPLETED:
        raise Http404
    if not can_access_lesson(enrollment, lesson):
        raise Http404

    video_id = lesson.youtube_id()
    if not video_id:
        raise Http404
    response = render(request, 'learning/secure_video.html', {
        'lesson': lesson,
        'course': course,
        'video_id': video_id,
        'watermark_text': f'{request.academy.name.upper()} · {request.user.email}',
    })
    response['Cache-Control'] = 'private, no-store, no-cache, must-revalidate, max-age=0'
    response['Referrer-Policy'] = 'no-referrer'
    response['Cross-Origin-Resource-Policy'] = 'same-origin'
    return response


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
    watermark = f'{request.academy.name.upper()} · {request.user.email} · {timezone.localtime().strftime("%Y-%m-%d %H:%M")}'
    image = _watermark_material_page(image, watermark)
    response = HttpResponse(image, content_type='image/jpeg')
    response['Content-Disposition'] = 'inline'
    response['Cache-Control'] = 'private, no-store, max-age=0'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cross-Origin-Resource-Policy'] = 'same-origin'
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
        return redirect('learning:my_courses')

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
        return redirect('learning:my_courses')
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
