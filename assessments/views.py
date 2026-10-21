import random

from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from core.decorators import professor_required, verified_email_required
from catalog.models import Course
from learning.models import Enrollment
from learning.services import course_navigation_context
from tenancy.services import scope_courses
from .forms import QuizForm, QuestionImportForm
from .importers import ALLOWED_TYPES, import_question_rows, read_question_xlsx, reuse_questions
from .models import Question, Quiz, QuizAttempt
from .services import get_or_create_attempt, submit_attempt


@verified_email_required
def quiz_take(request, quiz_id):
    quiz = get_object_or_404(Quiz.objects.select_related('course', 'module'), id=quiz_id, is_active=True)
    if not scope_courses(Course.objects.filter(pk=quiz.course_id), request.academy).exists():
        messages.error(request, 'Esta evaluación no pertenece a tu academia.')
        return redirect('learning:dashboard')
    enrollment = get_object_or_404(Enrollment, user=request.user, course=quiz.course)
    try:
        attempt = get_or_create_attempt(quiz, enrollment)
    except PermissionError as exc:
        # No redirigir al reproductor: el reproductor puede resolver nuevamente
        # esta misma evaluación como siguiente paso y generar un ciclo infinito
        # (ERR_TOO_MANY_REDIRECTS). Mostramos un estado estable y recuperable.
        context = {
            'quiz': quiz,
            'enrollment': enrollment,
            'reason': str(exc),
        }
        context.update(course_navigation_context(enrollment, active_quiz_id=quiz.id))
        return render(request, 'assessments/unavailable.html', context, status=409)

    require_identity = bool(settings.REQUIRE_FINAL_EXAM_IDENTITY_PHOTO and quiz.kind == Quiz.Kind.FINAL)
    if request.method == 'POST':
        if require_identity:
            photo = request.FILES.get('identity_photo')
            consent = request.POST.get('identity_consent') == 'on'
            if not photo or not consent:
                messages.error(request, 'Para este examen final debes autorizar y tomar/subir la fotografía de verificación.')
                return redirect('assessments:take', quiz.id)
            attempt.identity_photo = photo
            attempt.identity_consent = True
            attempt.save(update_fields=['identity_photo', 'identity_consent'])
        submit_attempt(attempt, request.POST)
        messages.success(request, 'Evaluación procesada automáticamente. Revisa tu resultado.')
        return redirect('assessments:result', attempt.id)

    questions = list(
        Question.objects.filter(id__in=attempt.question_ids, question_type__in=ALLOWED_TYPES)
        .prefetch_related('choices')
    )
    ordered = {str(q.id): q for q in questions}
    questions = [ordered[qid] for qid in attempt.question_ids if qid in ordered]
    question_data = []
    for question in questions:
        choices = list(question.choices.all())
        if quiz.randomize_choices:
            random.shuffle(choices)
        question_data.append((question, choices))
    context = {
        'quiz': quiz,
        'attempt': attempt,
        'question_data': question_data,
        'require_identity': require_identity,
    }
    context.update(course_navigation_context(enrollment, active_quiz_id=quiz.id))
    return render(request, 'assessments/take.html', context)


@verified_email_required
def result(request, attempt_id):
    attempt = get_object_or_404(
        QuizAttempt.objects.select_related('quiz__course', 'enrollment__user'),
        id=attempt_id,
        enrollment__user=request.user,
    )
    if not scope_courses(Course.objects.filter(pk=attempt.quiz.course_id), request.academy).exists():
        return redirect('learning:dashboard')

    answer_rows = []
    if attempt.quiz.show_correct_answers:
        answers = (
            attempt.answers.select_related('question')
            .prefetch_related('selected_choices', 'question__choices')
            .order_by('question__order', 'question__id')
        )
        for answer in answers:
            selected_ids = {choice.id for choice in answer.selected_choices.all()}
            choices = list(answer.question.choices.all())
            answer_rows.append({
                'answer': answer,
                'question': answer.question,
                'selected': [choice for choice in choices if choice.id in selected_ids],
                'correct': [choice for choice in choices if choice.is_correct],
            })

    context = {'attempt': attempt, 'answer_rows': answer_rows}
    context.update(course_navigation_context(attempt.enrollment, active_quiz_id=attempt.quiz.id))
    return render(request, 'assessments/result.html', context)


def _own_course(request, course_id):
    qs = scope_courses(Course.objects.all(), request.academy)
    if getattr(request, 'academy_role', '') != 'OWNER':
        qs = qs.filter(instructor_links__user=request.user)
    return get_object_or_404(qs.distinct(), id=course_id)


@professor_required
def quiz_create(request, course_id):
    course = _own_course(request, course_id)
    form = QuizForm(request.POST or None)
    form.fields['module'].queryset = course.modules.all()
    if request.method == 'POST' and form.is_valid():
        quiz = form.save(commit=False)
        quiz.course = course
        quiz.is_active = False
        if quiz.kind == Quiz.Kind.FINAL:
            quiz.module = None
        quiz.save()
        messages.success(request, 'Evaluación creada. Importa preguntas automáticas y revisa la vista previa antes de publicarla.')
        return redirect('assessments:professor_import_questions', quiz.id)
    return render(request, 'professor/simple_form.html', {
        'form': form,
        'title': f'Nueva evaluación · {course.title}',
        'helper': 'Las preguntas son de selección única o varias selecciones y se califican automáticamente.',
        'back_url': course.id,
    })


@professor_required
def import_questions_view(request, quiz_id):
    quiz = get_object_or_404(Quiz.objects.select_related('course'), id=quiz_id)
    _own_course(request, quiz.course_id)
    session_key = f'preview_preguntas_{quiz.id}'
    preview_rows = request.session.get(session_key, [])
    preview_errors = []
    form = QuestionImportForm(request.POST or None, request.FILES or None)

    owned_courses = scope_courses(Course.objects.all(), request.academy)
    if getattr(request, 'academy_role', '') != 'OWNER':
        owned_courses = owned_courses.filter(instructor_links__user=request.user)
    reusable = (
        Question.objects.filter(quiz__course__in=owned_courses, question_type__in=ALLOWED_TYPES)
        .exclude(quiz=quiz)
        .select_related('quiz__course')
        .prefetch_related('choices')
        .order_by('-quiz__created_at', 'order')[:200]
    )

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'publish':
            active_count = quiz.questions.filter(is_active=True, question_type__in=ALLOWED_TYPES).count()
            if active_count < quiz.question_count:
                messages.error(request, f'El banco tiene {active_count} preguntas automáticas y la evaluación necesita al menos {quiz.question_count}.')
            else:
                quiz.is_active = True
                quiz.save(update_fields=['is_active'])
                messages.success(request, 'Evaluación publicada. La calificación será automática.')
                return redirect('assessments:professor_import_questions', quiz.id)
        elif action == 'pause':
            quiz.is_active = False
            quiz.save(update_fields=['is_active'])
            messages.warning(request, 'Evaluación pausada.')
            return redirect('assessments:professor_import_questions', quiz.id)
        elif action == 'confirm':
            if not preview_rows:
                messages.error(request, 'No hay preguntas previsualizadas para importar.')
            elif preview_errors:
                messages.error(request, 'Corrige los errores del XLSX antes de importar.')
            else:
                count, errors = import_question_rows(quiz, preview_rows)
                request.session.pop(session_key, None)
                messages.success(request, f'{count} preguntas importadas al banco.')
                for error in errors[:10]:
                    messages.warning(request, error)
                return redirect('assessments:professor_import_questions', quiz.id)
        elif action == 'reuse':
            selected = request.POST.getlist('question_ids')
            count = reuse_questions(quiz, reusable.filter(id__in=selected))
            messages.success(request, f'{count} preguntas reutilizadas.')
            return redirect('assessments:professor_import_questions', quiz.id)
        elif form.is_valid():
            try:
                preview_rows, preview_errors = read_question_xlsx(form.cleaned_data['file'])
            except ValueError as exc:
                messages.error(request, str(exc))
                preview_rows = []
            else:
                request.session[session_key] = preview_rows
                request.session.modified = True

    current_questions = quiz.questions.filter(question_type__in=ALLOWED_TYPES).prefetch_related('choices').all()
    return render(request, 'professor/import_questions.html', {
        'form': form,
        'quiz': quiz,
        'preview_rows': preview_rows,
        'preview_errors': preview_errors,
        'reusable_questions': reusable,
        'current_questions': current_questions,
    })


@professor_required
def quiz_quick_settings(request, quiz_id):
    quiz = get_object_or_404(Quiz.objects.select_related('course'), id=quiz_id)
    _own_course(request, quiz.course_id)
    if request.method != 'POST':
        return redirect('catalog:professor_course_edit', quiz.course_id)

    quiz.show_correct_answers = request.POST.get('show_correct_answers') == 'on'
    raw_limit = (request.POST.get('attempt_limit') or '3').strip()
    allowed = {0, 1, 2, 3, 5}
    try:
        limit = int(raw_limit)
    except ValueError:
        limit = 3
    quiz.max_attempts = limit if limit in allowed else 3
    quiz.save(update_fields=['show_correct_answers', 'max_attempts'])
    label = 'ilimitados' if quiz.max_attempts == 0 else str(quiz.max_attempts)
    messages.success(request, f'Ajustes rápidos guardados: intentos {label}.')
    return redirect('catalog:professor_course_edit', quiz.course_id)


@professor_required
def review_attempt(request, attempt_id):
    """Compatibilidad con enlaces antiguos; ya no existen evaluaciones manuales."""
    attempt = get_object_or_404(QuizAttempt.objects.select_related('quiz__course'), pk=attempt_id)
    _own_course(request, attempt.quiz.course_id)
    messages.info(request, 'Las evaluaciones ahora se califican automáticamente; no hay respuestas pendientes de revisión manual.')
    return redirect('catalog:professor_students', attempt.quiz.course_id)
