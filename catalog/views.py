from uuid import UUID
import mimetypes

from django.contrib import messages
from django.core import signing
from django.http import FileResponse, Http404, HttpResponse
from django.db.models import Max, Avg, F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.template.defaultfilters import filesizeformat
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin

from core.decorators import professor_required
from tenancy.services import (
    academy_has_available_seat, bind_course, create_academy_category, resolve_public_academy,
    scope_categories, scope_courses,
)
from certificates.design import preview_style_context
from certificates.rendering import render_certificate_pdf
from audit.services import log_event
from billing.models import Order, Payment
from billing.services import approve_payment
from learning.models import Enrollment
from learning.services import progress_percentage
from assessments.models import Quiz, QuizAttempt
from tenancy.models import AcademyMembership
from .forms import CourseContentImportForm, CourseForm, CourseMasterclassForm, ModuleForm, LessonForm, ProfessorCategoryForm, ProfessorCertificateToggleForm
from .importers import import_course_content_rows, read_content_xlsx
from .models import Category, Course, CourseInstructor, Lesson, Module
from .pdf_tools import PDFMaterialError, pdf_page_count, render_pdf_page

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

    courses = list(courses)
    if request.user.is_authenticated and not request.user.is_superuser:
        from learning.models import Enrollment
        from learning.services import progress_percentage

        enrollments = {
            item.course_id: item
            for item in Enrollment.objects.filter(
                user=request.user,
                course_id__in=[course.id for course in courses],
            ).select_related('course')
        }
        for course in courses:
            course.student_enrollment = enrollments.get(course.id)
            course.student_progress = (
                progress_percentage(course.student_enrollment)
                if course.student_enrollment
                else 0
            )
    else:
        for course in courses:
            course.student_enrollment = None
            course.student_progress = 0

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
    enrollment_progress = progress_percentage(enrollment) if enrollment else 0
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
        'enrollment_progress': enrollment_progress,
    })


def _academy_courses_for_professor(request):
    qs = scope_courses(Course.objects.all(), request.academy)
    if getattr(request, 'academy_role', '') != 'OWNER':
        qs = qs.filter(instructor_links__user=request.user)
    return qs.distinct()


def _professor_can_manage_students(request):
    if getattr(request, 'academy_role', '') == AcademyMembership.Role.OWNER:
        return True
    membership = getattr(request, 'academy_membership', None)
    return bool(membership and membership.can_manage_student_payments)


def _student_rows_for_courses(courses, academy):
    """Construye el seguimiento académico manteniendo cada curso aislado.

    Para cada estudiante se devuelve el progreso general, promedio y el último
    resultado de cada cuestionario/examen del curso. Nunca se mezclan
    evaluaciones de otros cursos.
    """
    course_list = list(courses)
    course_ids = [course.id for course in course_list]
    enrollments = list(
        Enrollment.objects.filter(course_id__in=course_ids)
        .select_related('user', 'course')
        .order_by('course__title', 'user__first_name', 'user__last_name', 'user__email')
    )
    membership_map = {
        membership.user_id: membership
        for membership in AcademyMembership.objects.filter(
            academy=academy,
            user_id__in=[item.user_id for item in enrollments],
        )
    }

    quizzes_by_course = {}
    quizzes = list(
        Quiz.objects.filter(course_id__in=course_ids)
        .filter(Q(kind=Quiz.Kind.FINAL, module__isnull=True) | Q(kind=Quiz.Kind.MODULE, module__course_id=F('course_id')))
        .select_related('module')
        .order_by('course_id', 'kind', 'module__order', 'created_at')
    )
    for quiz in quizzes:
        quizzes_by_course.setdefault(quiz.course_id, []).append(quiz)

    attempts_by_enrollment = {}
    for attempt in (
        QuizAttempt.objects.filter(
            enrollment_id__in=[item.id for item in enrollments],
            submitted_at__isnull=False,
        )
        .select_related('quiz', 'quiz__module')
        .order_by('-submitted_at')
    ):
        attempts_by_enrollment.setdefault(attempt.enrollment_id, []).append(attempt)

    latest_payment = {}
    for payment in (
        Payment.objects.filter(order__course_id__in=course_ids)
        .select_related('order__user', 'order__course')
        .order_by('-created_at')
    ):
        latest_payment.setdefault((payment.order.course_id, payment.order.user_id), payment)

    rows = []
    for enrollment in enrollments:
        valid_quiz_ids = {quiz.id for quiz in quizzes_by_course.get(enrollment.course_id, [])}
        attempts = [
            attempt for attempt in attempts_by_enrollment.get(enrollment.id, [])
            if attempt.quiz_id in valid_quiz_ids
        ]
        scored = [float(attempt.score) for attempt in attempts if attempt.score is not None]
        latest_by_quiz = {}
        attempt_count_by_quiz = {}
        for attempt in attempts:
            attempt_count_by_quiz[attempt.quiz_id] = attempt_count_by_quiz.get(attempt.quiz_id, 0) + 1
            latest_by_quiz.setdefault(attempt.quiz_id, attempt)

        quiz_results = []
        for quiz in quizzes_by_course.get(enrollment.course_id, []):
            attempt = latest_by_quiz.get(quiz.id)
            quiz_results.append({
                'quiz': quiz,
                'attempt': attempt,
                'score': float(attempt.score) if attempt and attempt.score is not None else None,
                'passed': bool(attempt and attempt.passed),
                'attempts': attempt_count_by_quiz.get(quiz.id, 0),
                'label': (
                    f'Módulo {quiz.module.order}'
                    if quiz.kind == Quiz.Kind.MODULE and quiz.module
                    else 'Examen final'
                ),
            })

        rows.append({
            'enrollment': enrollment,
            'course': enrollment.course,
            'membership': membership_map.get(enrollment.user_id),
            'progress': progress_percentage(enrollment),
            'attempts': attempts,
            'quiz_results': quiz_results,
            'average_score': round(sum(scored) / len(scored), 1) if scored else None,
            'latest_score': scored[0] if scored else None,
            'latest_payment': latest_payment.get((enrollment.course_id, enrollment.user_id)),
        })
    return rows


@professor_required
def professor_dashboard(request):
    courses = _academy_courses_for_professor(request).select_related('category').order_by('-updated_at')
    course_ids = list(courses.values_list('id', flat=True))
    enrollments = Enrollment.objects.filter(course_id__in=course_ids)
    enrollment_list = list(enrollments.select_related('course', 'user'))
    progress_values = [progress_percentage(item) for item in enrollment_list]
    attempts = QuizAttempt.objects.filter(
        enrollment__course_id__in=course_ids, submitted_at__isnull=False, score__isnull=False
    )
    average_grade = attempts.aggregate(value=Avg('score'))['value']
    stats = {
        'courses': len(course_ids),
        'published': courses.filter(status__in=PUBLIC_STATUSES).count(),
        'enrollments': len(enrollment_list),
        'students': enrollments.values('user_id').distinct().count(),
        'pending_payments': Payment.objects.filter(
            order__course_id__in=course_ids, status=Payment.Status.PENDING
        ).count(),
        'average_progress': round(sum(progress_values) / len(progress_values)) if progress_values else 0,
        'average_grade': round(float(average_grade), 1) if average_grade is not None else None,
        'review': courses.filter(status=Course.Status.REVIEW).count(),
    }
    recent_courses = list(courses[:5])
    pending_payments = list(
        Payment.objects.filter(order__course_id__in=course_ids, status=Payment.Status.PENDING)
        .select_related('order__course', 'order__user')
        .order_by('-created_at')[:5]
    )
    return render(request, 'professor/dashboard.html', {
        'stats': stats,
        'recent_courses': recent_courses,
        'pending_payments': pending_payments,
        'can_manage_students': _professor_can_manage_students(request),
        'academy': request.academy,
    })


@professor_required
def professor_courses(request):
    courses = list(
        _academy_courses_for_professor(request)
        .select_related('category')
        .prefetch_related('modules', 'quizzes', 'enrollments')
        .order_by('-updated_at')
    )
    return render(request, 'professor/courses.html', {
        'courses': courses,
        'academy': request.academy,
    })


@professor_required
def professor_students_overview(request):
    courses = list(
        _academy_courses_for_professor(request)
        .select_related('category')
        .order_by('title')
    )
    course_rows = []
    for course in courses:
        enrollments = list(
            Enrollment.objects.filter(course=course)
            .select_related('user')
            .order_by('user__first_name', 'user__last_name', 'user__email')
        )
        progress_values = [progress_percentage(item) for item in enrollments]
        attempts = QuizAttempt.objects.filter(
            enrollment__course=course,
            submitted_at__isnull=False,
            score__isnull=False,
        )
        average_grade = attempts.aggregate(value=Avg('score'))['value']
        pending_payments = Payment.objects.filter(
            order__course=course,
            status=Payment.Status.PENDING,
        ).count()
        course_rows.append({
            'course': course,
            'students': len({item.user_id for item in enrollments}),
            'enrollments': len(enrollments),
            'average_progress': round(sum(progress_values) / len(progress_values)) if progress_values else 0,
            'average_grade': round(float(average_grade), 1) if average_grade is not None else None,
            'pending_payments': pending_payments,
        })

    return render(request, 'professor/students_overview.html', {
        'course_rows': course_rows,
        'can_manage_students': _professor_can_manage_students(request),
    })


@professor_required
def professor_categories(request):
    categories = scope_categories(Category.objects.all(), request.academy).select_related('parent').order_by('order', 'name')
    form = ProfessorCategoryForm(request.POST or None, academy=request.academy)
    if request.method == 'POST' and form.is_valid():
        category, created = create_academy_category(
            request.academy,
            form.cleaned_data['name'],
            description=form.cleaned_data.get('description', ''),
            parent=form.cleaned_data.get('parent'),
            is_active=True,
            order=categories.count(),
        )
        if not created:
            form.add_error('name', 'Esta categoría ya existe. Selecciónala al crear o editar el curso.')
        else:
            log_event(request.user, 'categoria_profesor_creada', category, {'academia': request.academy.slug}, request)
            messages.success(request, f'Categoría “{category.name}” creada. Ya está disponible también para el dueño y los demás profesores de esta academia.')
            return redirect('catalog:professor_categories')
    return render(request, 'professor/categories.html', {
        'categories_list': categories,
        'form': form,
    })


@professor_required
def course_create(request):
    form = CourseForm(request.POST or None, request.FILES or None, academy=request.academy)
    if request.method == 'POST' and form.is_valid():
        course = form.save(commit=False)
        course.created_by = request.user
        course.status = Course.Status.DRAFT
        # La certificación se configura exclusivamente en su apartado para evitar duplicados.
        course.certificate_enabled = False
        course.certificate_style_mode = Course.CertificateStyleMode.ACADEMY
        course.save()
        bind_course(course, request.academy)
        CourseInstructor.objects.get_or_create(course=course, user=request.user, defaults={'is_owner': True})
        messages.success(request, 'Curso creado como borrador. Ahora agrega módulos, clases y evaluaciones.')
        return redirect('catalog:professor_course_edit', course.pk)
    return render(request, 'professor/course_form.html', {'form': form, 'title': 'Crear curso'})


def _professor_course(request, pk):
    qs = scope_courses(Course.objects.all(), request.academy)
    if getattr(request, 'academy_role', '') != 'OWNER':
        qs = qs.filter(instructor_links__user=request.user)
    return get_object_or_404(qs.distinct(), pk=pk)


PROFESSOR_PREVIEW_VIDEO_SALT = 'catalog.professor-student-preview-video.v1'
PROFESSOR_PREVIEW_VIDEO_MAX_AGE = 60 * 20


def _preview_visible_modules(course):
    """Contenido que un estudiante podría ver una vez publicado.

    La vista previa del profesor permite navegar libremente entre esos pasos,
    pero nunca crea matrículas, progreso, intentos ni certificados.
    """
    modules = list(
        course.modules.filter(is_published=True)
        .prefetch_related('lessons', 'quizzes')
        .order_by('order', 'id')
    )
    for module in modules:
        lessons = [lesson for lesson in module.lessons.all() if lesson.is_published]
        lessons.sort(key=lambda item: (item.order, str(item.id)))
        for lesson in lessons:
            lesson.student_can_open = True
            lesson.student_completed = False
        module.nav_lessons = lessons

        quizzes = [quiz for quiz in module.quizzes.all() if quiz.is_active]
        quizzes.sort(key=lambda item: (item.created_at, str(item.id)))
        for quiz in quizzes:
            quiz.student_can_open = True
            quiz.student_passed = False
            quiz.student_result_attempt_id = None
        module.nav_quizzes = quizzes
    return modules


def _preview_final_quizzes(course):
    quizzes = list(
        course.quizzes.filter(
            module__isnull=True,
            kind=Quiz.Kind.FINAL,
            is_active=True,
        ).order_by('created_at', 'id')
    )
    for quiz in quizzes:
        quiz.student_can_open = True
        quiz.student_passed = False
        quiz.student_result_attempt_id = None
    return quizzes


def _preview_steps(course):
    """Ruta navegable del modo profesor, sin reglas de bloqueo ni escritura."""
    steps = []
    modules = _preview_visible_modules(course)
    for module in modules:
        for lesson in module.nav_lessons:
            steps.append({'kind': 'lesson', 'object': lesson, 'module': module})
        for quiz in module.nav_quizzes:
            steps.append({'kind': 'quiz', 'object': quiz, 'module': module})
    for quiz in _preview_final_quizzes(course):
        steps.append({'kind': 'quiz', 'object': quiz, 'module': None})
    if course.masterclass_enabled:
        steps.append({'kind': 'masterclass', 'object': course, 'module': None})
    return steps


def _preview_step_url(course, step):
    if not step:
        return reverse('catalog:professor_course_edit', kwargs={'pk': course.id})
    if step['kind'] == 'lesson':
        return reverse('catalog:professor_student_preview_lesson', kwargs={
            'pk': course.id,
            'lesson_id': step['object'].id,
        })
    if step['kind'] == 'quiz':
        return reverse('catalog:professor_student_preview_quiz', kwargs={
            'pk': course.id,
            'quiz_id': step['object'].id,
        })
    return reverse('catalog:professor_student_preview_masterclass', kwargs={'pk': course.id})


def _preview_step_label(current, target, *, forward=True):
    if not target:
        return 'Finalizar vista previa' if forward else 'Volver'
    if target['kind'] == 'quiz':
        if target['object'].kind == Quiz.Kind.FINAL:
            return 'Ir al examen final'
        return 'Continuar al cuestionario' if forward else 'Cuestionario anterior'
    if target['kind'] == 'masterclass':
        return 'Ir a clase magistral'
    if current and current.get('module') and target.get('module') and current['module'].id != target['module'].id:
        return 'Siguiente módulo' if forward else 'Módulo anterior'
    return 'Siguiente clase' if forward else 'Anterior'


def _preview_flow(course, *, kind, object_id=None):
    steps = _preview_steps(course)
    current_index = None
    for index, step in enumerate(steps):
        if step['kind'] != kind:
            continue
        if kind == 'masterclass' or str(step['object'].id) == str(object_id):
            current_index = index
            break
    if current_index is None:
        return {'preview_previous_url': '', 'preview_next_url': '', 'preview_next_label': 'Finalizar vista previa'}
    current = steps[current_index]
    previous = steps[current_index - 1] if current_index > 0 else None
    following = steps[current_index + 1] if current_index + 1 < len(steps) else None
    return {
        'preview_previous_url': _preview_step_url(course, previous) if previous else '',
        'preview_previous_label': _preview_step_label(current, previous, forward=False),
        'preview_next_url': _preview_step_url(course, following),
        'preview_next_label': _preview_step_label(current, following, forward=True),
        'preview_is_last_step': following is None,
    }


def _professor_preview_navigation(course, *, active_lesson_id=None, active_quiz_id=None, active_masterclass=False):
    return {
        'course': course,
        'course_nav_modules': _preview_visible_modules(course),
        'course_nav_final_quizzes': _preview_final_quizzes(course),
        'course_progress_percentage': 0,
        'active_lesson_id': active_lesson_id,
        'active_quiz_id': active_quiz_id,
        'active_masterclass': active_masterclass,
        'professor_student_preview': True,
    }


def _professor_preview_material_context(course, lesson):
    if not lesson.material_pdf:
        return {'material_page_count': 0, 'material_page_urls': [], 'material_pdf_size': 0}
    try:
        count = pdf_page_count(lesson.material_pdf)
        urls = [
            reverse('catalog:professor_student_preview_material', kwargs={
                'pk': course.id,
                'lesson_id': lesson.id,
                'page_number': page,
            })
            for page in range(1, count + 1)
        ]
        try:
            size = lesson.material_pdf.size
        except (OSError, ValueError):
            size = 0
        return {'material_page_count': count, 'material_page_urls': urls, 'material_pdf_size': size}
    except PDFMaterialError:
        return {'material_page_count': 0, 'material_page_urls': [], 'material_pdf_size': 0}


@professor_required
def professor_student_preview(request, pk):
    course = _professor_course(request, pk)
    steps = _preview_steps(course)
    module_id = (request.GET.get('module') or '').strip()
    preview_module = None
    if module_id:
        try:
            preview_module = course.modules.get(pk=module_id)
        except (Module.DoesNotExist, ValueError):
            preview_module = None
        if preview_module:
            module_steps = [step for step in steps if step.get('module') and step['module'].id == preview_module.id]
            if module_steps:
                return redirect(_preview_step_url(course, module_steps[0]))
    if not steps:
        return render(request, 'professor/student_preview_empty.html', {
            'course': course,
            'module': preview_module,
            'professor_student_preview': True,
        })
    return redirect(_preview_step_url(course, steps[0]))


@professor_required
def professor_student_preview_lesson(request, pk, lesson_id):
    course = _professor_course(request, pk)
    lesson = get_object_or_404(
        Lesson.objects.select_related('module', 'module__course'),
        id=lesson_id,
        module__course=course,
        module__is_published=True,
        is_published=True,
    )

    video_frame_url = ''
    if lesson.youtube_id():
        token = signing.dumps({
            'preview': True,
            'lesson_id': str(lesson.id),
            'course_id': str(course.id),
            'user_id': str(request.user.id),
            'academy_id': str(request.academy.id),
        }, salt=PROFESSOR_PREVIEW_VIDEO_SALT, compress=True)
        video_frame_url = reverse('catalog:professor_student_preview_video', kwargs={
            'pk': course.id,
            'lesson_id': lesson.id,
            'token': token,
        })

    marker = 'Contenido extraído del material PDF:'
    description = lesson.description or ''
    lesson_summary = description.split(marker, 1)[0].strip() if marker in description else description.strip()
    context = {
        'course': course,
        'lesson': lesson,
        'lesson_summary': lesson_summary,
        'progress': {'completed': False},
        'video_frame_url': video_frame_url,
    }
    context.update(_professor_preview_material_context(course, lesson))
    context.update(_professor_preview_navigation(course, active_lesson_id=lesson.id))
    context.update(_preview_flow(course, kind='lesson', object_id=lesson.id))
    return render(request, 'learning/lesson.html', context)


@professor_required
def professor_student_preview_quiz(request, pk, quiz_id):
    course = _professor_course(request, pk)
    quiz = get_object_or_404(
        Quiz.objects.select_related('course', 'module'),
        id=quiz_id,
        course=course,
        is_active=True,
    )
    if quiz.kind == Quiz.Kind.MODULE and (not quiz.module_id or not quiz.module.is_published):
        raise Http404

    questions = list(quiz.questions.filter(is_active=True).prefetch_related('choices').order_by('order', 'id'))
    questions = questions[:max(quiz.question_count, 1)]
    question_data = [(question, list(question.choices.all())) for question in questions]
    minutes = quiz.time_limit_minutes or 0
    timing = {
        'mode': quiz.time_mode,
        'limit_minutes': minutes,
        'limit_seconds': minutes * 60,
        'elapsed_seconds': 0,
        'remaining_seconds': minutes * 60,
        'elapsed_label': '00:00',
        'remaining_label': f'{minutes:02d}:00' if minutes < 60 else f'{minutes // 60}:{minutes % 60:02d}:00',
    }
    context = {
        'course': course,
        'quiz': quiz,
        'question_data': question_data,
        'timing': timing,
        'require_identity': False,
        'preview_identity_required': quiz.kind == Quiz.Kind.FINAL,
    }
    context.update(_professor_preview_navigation(course, active_quiz_id=quiz.id))
    context.update(_preview_flow(course, kind='quiz', object_id=quiz.id))
    return render(request, 'assessments/take.html', context)


@professor_required
def professor_student_preview_masterclass(request, pk):
    course = _professor_course(request, pk)
    if not course.masterclass_enabled:
        raise Http404
    context = {'course': course}
    context.update(_professor_preview_navigation(course, active_masterclass=True))
    context.update(_preview_flow(course, kind='masterclass'))
    return render(request, 'learning/masterclass.html', context)


@xframe_options_sameorigin
@professor_required
def professor_student_preview_video(request, pk, lesson_id, token):
    course = _professor_course(request, pk)
    try:
        payload = signing.loads(
            token,
            salt=PROFESSOR_PREVIEW_VIDEO_SALT,
            max_age=PROFESSOR_PREVIEW_VIDEO_MAX_AGE,
        )
    except signing.BadSignature as exc:
        raise Http404 from exc
    lesson = get_object_or_404(
        Lesson.objects.select_related('module', 'module__course'),
        id=lesson_id,
        module__course=course,
        module__is_published=True,
        is_published=True,
    )
    expected = {
        'preview': 'True',
        'lesson_id': str(lesson.id),
        'course_id': str(course.id),
        'user_id': str(request.user.id),
        'academy_id': str(request.academy.id),
    }
    if any(str(payload.get(key, '')) != value for key, value in expected.items()):
        raise Http404
    video_id = lesson.youtube_id()
    if not video_id:
        raise Http404
    response = render(request, 'learning/secure_video.html', {
        'lesson': lesson,
        'course': course,
        'video_id': video_id,
        'watermark_text': f'VISTA PREVIA PROFESOR · {request.user.email}',
    })
    response['Cache-Control'] = 'private, no-store, no-cache, must-revalidate, max-age=0'
    response['Referrer-Policy'] = 'no-referrer'
    response['Cross-Origin-Resource-Policy'] = 'same-origin'
    return response


@professor_required
def professor_student_preview_material(request, pk, lesson_id, page_number):
    course = _professor_course(request, pk)
    lesson = get_object_or_404(
        Lesson.objects.select_related('module', 'module__course'),
        id=lesson_id,
        module__course=course,
        module__is_published=True,
        is_published=True,
    )
    if not lesson.material_pdf:
        raise Http404
    try:
        image = render_pdf_page(lesson.material_pdf, page_number)
    except PDFMaterialError as exc:
        raise Http404 from exc
    # Mantiene el mismo aspecto protegido que verá el estudiante, pero deja
    # claro que el contenido corresponde a una simulación del profesor.
    from learning.views import _watermark_material_page
    image = _watermark_material_page(
        image,
        f'{request.academy.name.upper()} · VISTA PREVIA · {request.user.email}',
    )
    response = HttpResponse(image, content_type='image/jpeg')
    response['Content-Disposition'] = 'inline'
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@professor_required
def course_edit(request, pk):
    course = _professor_course(request, pk)
    section = request.POST.get('section') if request.method == 'POST' else ''

    # Cada bloque se guarda de forma independiente para mantener la interfaz rápida.
    form = CourseForm(instance=course, academy=request.academy)
    form.fields.pop('certificate_enabled', None)
    form.fields.pop('certificate_style_mode', None)
    certificate_form = ProfessorCertificateToggleForm(course=course, prefix='certificate')
    masterclass_form = CourseMasterclassForm(instance=course, prefix='masterclass')

    if request.method == 'POST' and section == 'certificate':
        certificate_form = ProfessorCertificateToggleForm(request.POST, course=course, prefix='certificate')
        if certificate_form.is_valid():
            was_public = course.status in PUBLIC_STATUSES
            obj = certificate_form.save()
            if was_public:
                obj.status = Course.Status.REVIEW
                obj.save(update_fields=['status', 'updated_at'])
            messages.success(request, 'Certificación actualizada. El diseño y la apariencia los administra el dueño de la academia.')
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
        'final_quizzes': course.quizzes.filter(kind=Quiz.Kind.FINAL),
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
        messages.success(request, 'Módulo creado. Ahora configúralo completo antes de volver al curso.')
        return redirect('catalog:professor_module_editor', module.pk)
    return render(request, 'professor/simple_form.html', {
        'form': form,
        'title': f'Nuevo módulo · {course.title}',
        'helper': 'Define el nombre y el objetivo del módulo. Al guardarlo entrarás directamente a su espacio de trabajo.',
        'back_url': course.id,
    })


def _professor_module(request, module_pk):
    module = get_object_or_404(Module.objects.select_related('course'), pk=module_pk)
    _professor_course(request, module.course_id)
    return module


def _lesson_section_type(lesson):
    if lesson.video_source:
        return LessonForm.SECTION_VIDEO
    if lesson.material_pdf:
        return LessonForm.SECTION_PDF
    return LessonForm.SECTION_INSTRUCTIONS


@professor_required
def module_editor(request, module_pk):
    module = _professor_module(request, module_pk)
    course = module.course
    edit_lesson = None
    edit_id = (request.GET.get('editar') or '').strip()
    if edit_id:
        try:
            edit_lesson = module.lessons.get(pk=edit_id)
        except (Lesson.DoesNotExist, ValueError):
            edit_lesson = None

    module_form = ModuleForm(instance=module, prefix='module')
    section_form = LessonForm(instance=edit_lesson, prefix='section')
    action = request.POST.get('action') if request.method == 'POST' else ''

    if request.method == 'POST' and action == 'save_module':
        module_form = ModuleForm(request.POST, instance=module, prefix='module')
        if module_form.is_valid():
            module_form.save()
            messages.success(request, 'Datos del módulo guardados.')
            return redirect('catalog:professor_module_editor', module.pk)

    elif request.method == 'POST' and action == 'save_section':
        lesson_id = (request.POST.get('lesson_id') or '').strip()
        target = get_object_or_404(module.lessons.all(), pk=lesson_id) if lesson_id else None
        edit_lesson = target
        section_form = LessonForm(request.POST, request.FILES, instance=target, prefix='section')
        if section_form.is_valid():
            lesson = section_form.save(commit=False)
            lesson.module = module
            if not target:
                lesson.order = (module.lessons.aggregate(value=Max('order'))['value'] or 0) + 1
            lesson.is_preview = False
            lesson.is_published = True
            lesson.save()
            info = getattr(section_form, 'pdf_optimization_info', None)
            if info:
                before = filesizeformat(info['original_size'])
                after = filesizeformat(info['optimized_size'])
                messages.success(request, f'Sección guardada. PDF optimizado: {before} → {after} · {info["pages"]} página(s).')
            else:
                messages.success(request, 'Sección guardada dentro del módulo.')
            return redirect('catalog:professor_module_editor', module.pk)

    elif request.method == 'POST' and action == 'delete_section':
        lesson = get_object_or_404(module.lessons.all(), pk=request.POST.get('lesson_id'))
        lesson.delete()
        for index, item in enumerate(module.lessons.order_by('order', 'id'), start=1):
            if item.order != index:
                item.order = index
                item.save(update_fields=['order'])
        messages.warning(request, 'Sección eliminada del módulo.')
        return redirect('catalog:professor_module_editor', module.pk)

    elif request.method == 'POST' and action in {'move_up', 'move_down'}:
        lesson = get_object_or_404(module.lessons.all(), pk=request.POST.get('lesson_id'))
        siblings = list(module.lessons.order_by('order', 'id'))
        current_index = next((index for index, item in enumerate(siblings) if item.pk == lesson.pk), None)
        if current_index is not None:
            target_index = current_index - 1 if action == 'move_up' else current_index + 1
            if 0 <= target_index < len(siblings):
                other = siblings[target_index]
                current_order, other_order = lesson.order, other.order
                temporary = (module.lessons.aggregate(value=Max('order'))['value'] or 0) + 100
                lesson.order = temporary
                lesson.save(update_fields=['order'])
                other.order = current_order
                other.save(update_fields=['order'])
                lesson.order = other_order
                lesson.save(update_fields=['order'])
        return redirect('catalog:professor_module_editor', module.pk)

    lessons = list(module.lessons.order_by('order', 'id'))
    for lesson in lessons:
        lesson.section_type_label = dict(LessonForm.SECTION_CHOICES).get(_lesson_section_type(lesson), 'Sección')
    module_quizzes = module.quizzes.filter(kind=Quiz.Kind.MODULE).order_by('created_at')
    module_quiz = module_quizzes.first()

    return render(request, 'professor/module_editor.html', {
        'course': course,
        'module': module,
        'module_form': module_form,
        'section_form': section_form,
        'editing_lesson': edit_lesson,
        'lessons': lessons,
        'module_quiz': module_quiz,
        'duplicate_quiz_count': max(module_quizzes.count() - 1, 0),
    })


@professor_required
def lesson_create(request, module_pk):
    # Compatibilidad con enlaces anteriores: toda la edición vive dentro del módulo.
    module = _professor_module(request, module_pk)
    return redirect('catalog:professor_module_editor', module.pk)


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
    course = _professor_course(request, pk)
    rows = _student_rows_for_courses([course], request.academy)
    payments = list(
        Payment.objects.filter(order__course=course)
        .select_related('order__user', 'order__course')
        .order_by('-created_at')[:120]
    )
    progress_values = [row['progress'] for row in rows]
    scored_rows = [row['average_score'] for row in rows if row['average_score'] is not None]
    stats = {
        'students': len({row['enrollment'].user_id for row in rows}),
        'average_progress': round(sum(progress_values) / len(progress_values)) if progress_values else 0,
        'average_grade': round(sum(scored_rows) / len(scored_rows), 1) if scored_rows else None,
        'pending_payments': sum(1 for payment in payments if payment.status == Payment.Status.PENDING),
        'quizzes': Quiz.objects.filter(course=course).filter(Q(kind=Quiz.Kind.FINAL, module__isnull=True) | Q(kind=Quiz.Kind.MODULE, module__course=course)).count(),
    }
    return render(request, 'professor/students.html', {
        'course': course,
        'rows': rows,
        'payments': payments,
        'stats': stats,
        'can_manage_students': _professor_can_manage_students(request),
    })


@professor_required
def professor_payment_action(request, payment_id):
    if request.method != 'POST':
        return redirect('catalog:professor_students_overview')
    if not _professor_can_manage_students(request):
        messages.error(request, 'El dueño de la academia no te ha delegado permisos para gestionar pagos.')
        return redirect('catalog:professor_students_overview')
    course_ids = _academy_courses_for_professor(request).values_list('id', flat=True)
    payment = get_object_or_404(
        Payment.objects.select_related('order__course', 'order__user'),
        pk=payment_id,
        order__course_id__in=course_ids,
    )
    action = request.POST.get('action')
    if payment.status != Payment.Status.PENDING:
        messages.info(request, 'Este comprobante ya fue procesado.')
    elif action == 'approve':
        membership = AcademyMembership.objects.filter(
            academy=request.academy, user_id=payment.order.user_id, role=AcademyMembership.Role.STUDENT
        ).first()
        if not membership:
            messages.error(request, 'No se puede aprobar: este usuario todavía no está registrado como estudiante de la academia.')
            return redirect('catalog:professor_students', pk=payment.order.course_id)
        if membership.status != AcademyMembership.Status.ACTIVE:
            if not academy_has_available_seat(
                request.academy, AcademyMembership.Role.STUDENT, exclude_membership=membership
            ):
                messages.error(request, 'No hay cupos disponibles para activar a este estudiante.')
                return redirect('catalog:professor_students', pk=payment.order.course_id)
            membership.status = AcademyMembership.Status.ACTIVE
            membership.approved_at = timezone.now()
            membership.approved_by_id = request.user.pk
            membership.save(update_fields=['status', 'approved_at', 'approved_by_id'])
        try:
            enrollment = approve_payment(payment, request.user)
        except PermissionError as exc:
            messages.error(request, str(exc))
            return redirect('catalog:professor_students', pk=payment.order.course_id)
        messages.success(request, f'Pago aprobado. {enrollment.user.display_name} ya tiene acceso a “{payment.order.course.title}”.')
    elif action == 'reject':
        payment.status = Payment.Status.REJECTED
        payment.approved_by = request.user
        payment.approved_at = timezone.now()
        payment.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        messages.warning(request, f'Comprobante de {payment.order.user.display_name} rechazado.')
    else:
        messages.error(request, 'Acción de pago no válida.')
    log_event(
        request.user,
        f'pago_profesor_{action}',
        payment,
        {'curso': str(payment.order.course_id)},
        request,
    )
    if request.POST.get('return_to') == 'course':
        return redirect('catalog:professor_students', pk=payment.order.course_id)
    return redirect('catalog:professor_students_overview')


@professor_required
def professor_payment_proof(request, payment_id):
    if not _professor_can_manage_students(request):
        raise Http404
    course_ids = _academy_courses_for_professor(request).values_list('id', flat=True)
    payment = get_object_or_404(
        Payment.objects.select_related('order__course'),
        pk=payment_id,
        order__course_id__in=course_ids,
    )
    if not payment.proof:
        raise Http404
    response = FileResponse(payment.proof.open('rb'))
    response['Content-Disposition'] = f'inline; filename="comprobante-{payment.order.code}"'
    response['Cache-Control'] = 'private, no-store, max-age=0'
    return response


@professor_required
def professor_student_access_action(request, course_id, user_id):
    if request.method != 'POST':
        return redirect('catalog:professor_students', pk=course_id)
    course = _professor_course(request, course_id)
    if not _professor_can_manage_students(request):
        messages.error(request, 'El dueño no te ha delegado permisos para habilitar estudiantes.')
        return redirect('catalog:professor_students', pk=course.id)
    related = (
        Enrollment.objects.filter(course=course, user_id=user_id).exists()
        or Order.objects.filter(course=course, user_id=user_id).exists()
    )
    if not related:
        raise Http404
    membership = get_object_or_404(
        AcademyMembership, academy=request.academy, user_id=user_id, role=AcademyMembership.Role.STUDENT
    )
    if not academy_has_available_seat(
        request.academy, AcademyMembership.Role.STUDENT, exclude_membership=membership
    ):
        messages.error(request, 'No hay cupos disponibles para habilitar este estudiante.')
        return redirect('catalog:professor_students', pk=course.id)
    membership.status = AcademyMembership.Status.ACTIVE
    membership.approved_at = timezone.now()
    membership.approved_by_id = request.user.pk
    membership.save(update_fields=['status', 'approved_at', 'approved_by_id'])
    Enrollment.objects.filter(
        course=course, user_id=user_id, status__in=[Enrollment.Status.BLOCKED, Enrollment.Status.REVOKED]
    ).update(status=Enrollment.Status.ACTIVE, blocked_reason='')
    messages.success(request, 'Cuenta y acceso del estudiante habilitados para continuar el curso.')
    log_event(request.user, 'estudiante_habilitado_profesor', membership, {'curso': str(course.id)}, request)
    return redirect('catalog:professor_students', pk=course.id)
