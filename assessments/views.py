import random

from django.conf import settings
from django import forms as django_forms
from django.contrib import messages
from django.http import QueryDict
from django.shortcuts import get_object_or_404, redirect, render

from core.decorators import professor_required, verified_email_required
from catalog.models import Course
from learning.models import Enrollment
from learning.services import course_navigation_context
from tenancy.services import scope_courses
from .forms import QuizForm, QuizSettingsForm, QuestionImportForm
from .importers import ALLOWED_TYPES, QUESTION_BANK_ARCHIVE_OFFSET, import_question_rows, read_question_xlsx
from .models import Question, Quiz, QuizAttempt
from .services import HARD_TIMER_GRACE_SECONDS, attempt_timing, get_or_create_attempt, submit_attempt


@verified_email_required
def quiz_take(request, quiz_id):
    quiz = get_object_or_404(Quiz.objects.select_related('course', 'module'), id=quiz_id, is_active=True)
    if not scope_courses(Course.objects.filter(pk=quiz.course_id), request.academy).exists():
        messages.error(request, 'Esta evaluación no pertenece a tu academia.')
        return redirect('learning:my_courses')
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

    timing = attempt_timing(attempt)
    require_identity = bool(settings.REQUIRE_FINAL_EXAM_IDENTITY_PHOTO and quiz.kind == Quiz.Kind.FINAL)
    if request.method == 'POST':
        timer_expired_signal = request.POST.get('_timer_expired') == '1'
        if require_identity:
            photo = request.FILES.get('identity_photo')
            consent = request.POST.get('identity_consent') == 'on'
            if (not photo or not consent) and not timer_expired_signal and not timing['hard_expired']:
                messages.error(request, 'Para este examen final debes autorizar y tomar/subir la fotografía de verificación.')
                return redirect('assessments:take', quiz.id)
            if photo and consent:
                attempt.identity_photo = photo
                attempt.identity_consent = True
                attempt.save(update_fields=['identity_photo', 'identity_consent'])
        post_data = request.POST
        hard_timeout = bool(
            attempt.time_mode_snapshot == Quiz.TimeMode.LIMIT
            and timing['limit_seconds']
            and timing['elapsed_seconds'] > timing['limit_seconds'] + HARD_TIMER_GRACE_SECONDS
        )
        if hard_timeout:
            post_data = QueryDict('', mutable=False)
            messages.warning(request, 'El tiempo límite terminó. El intento se cerró automáticamente y no se aceptaron cambios realizados fuera del tiempo permitido.')
        submit_attempt(attempt, post_data, timed_out=(timer_expired_signal or timing['hard_expired']))
        if not hard_timeout:
            messages.success(request, 'Evaluación procesada automáticamente. Revisa tu resultado.')
        return redirect('assessments:result', attempt.id)

    questions = list(
        Question.objects.filter(id__in=attempt.question_ids, quiz=quiz, question_type__in=ALLOWED_TYPES)
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
        'timing': timing,
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
        return redirect('learning:my_courses')

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

    context = {'attempt': attempt, 'answer_rows': answer_rows, 'timing': attempt_timing(attempt)}
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
    forced_module = None
    module_id = (request.GET.get('module') or '').strip()
    forced_final = (request.GET.get('kind') or '').upper() == Quiz.Kind.FINAL
    if module_id:
        forced_module = get_object_or_404(course.modules.all(), pk=module_id)
        forced_final = False
        existing_module_quiz = course.quizzes.filter(kind=Quiz.Kind.MODULE, module=forced_module).first()
        if existing_module_quiz:
            messages.info(request, 'Este módulo ya tiene un cuestionario. Abrimos su configuración existente para evitar duplicados.')
            return redirect('assessments:professor_import_questions', existing_module_quiz.id)
    if forced_final:
        existing_final = course.quizzes.filter(kind=Quiz.Kind.FINAL).first()
        if existing_final:
            messages.info(request, 'El curso ya tiene un examen final. Abrimos su configuración existente.')
            return redirect('assessments:professor_import_questions', existing_final.id)

    initial = {}
    if forced_module:
        initial.update({
            'module': forced_module,
            'kind': Quiz.Kind.MODULE,
            'title': f'Cuestionario · {forced_module.title}',
        })
    elif forced_final:
        initial.update({
            'module': None,
            'kind': Quiz.Kind.FINAL,
            'title': 'Examen final',
        })

    form = QuizForm(request.POST or None, initial=initial)
    form.fields['module'].queryset = course.modules.all()
    if forced_module:
        form.fields['module'].widget = django_forms.HiddenInput()
        form.fields['kind'].widget = django_forms.HiddenInput()
    elif forced_final:
        form.fields['module'].widget = django_forms.HiddenInput()
        form.fields['kind'].widget = django_forms.HiddenInput()

    if request.method == 'POST' and form.is_valid():
        quiz = form.save(commit=False)
        quiz.course = course
        quiz.is_active = False
        if forced_module:
            quiz.kind = Quiz.Kind.MODULE
            quiz.module = forced_module
        elif forced_final or quiz.kind == Quiz.Kind.FINAL:
            quiz.kind = Quiz.Kind.FINAL
            quiz.module = None
        quiz.save()
        messages.success(request, 'Evaluación creada. Configura sus parámetros e importa el XLSX de preguntas.')
        return redirect('assessments:professor_import_questions', quiz.id)

    if forced_module:
        title = f'Cuestionario · {forced_module.title}'
        helper = 'Este cuestionario quedará dentro del módulo. Después podrás importar el XLSX y publicar la evaluación.'
    elif forced_final:
        title = f'Examen final · {course.title}'
        helper = 'Configura el examen final. Después podrás importar el XLSX, revisar el banco y publicarlo.'
    else:
        title = f'Nueva evaluación · {course.title}'
        helper = 'Las preguntas son de selección única o varias selecciones y se califican automáticamente.'
    return render(request, 'professor/simple_form.html', {
        'form': form,
        'title': title,
        'helper': helper,
        'back_url': course.id,
        'back_module_id': forced_module.id if forced_module else None,
    })


@professor_required
def import_questions_view(request, quiz_id):
    quiz = get_object_or_404(Quiz.objects.select_related('course', 'module'), id=quiz_id)
    _own_course(request, quiz.course_id)
    session_key = f'preview_preguntas_{quiz.id}'
    preview_rows = request.session.get(session_key, [])
    preview_errors = []
    action = request.POST.get('action') if request.method == 'POST' else ''
    form = QuestionImportForm(
        request.POST if request.method == 'POST' and not action else None,
        request.FILES if request.method == 'POST' and not action else None,
    )
    settings_form = QuizSettingsForm(
        request.POST if action == 'settings' else None,
        instance=quiz,
        prefix='settings',
    )

    if request.method == 'POST':
        if action == 'settings':
            if settings_form.is_valid():
                settings_form.save()
                messages.success(request, 'Parámetros de evaluación guardados.')
                return redirect('assessments:professor_import_questions', quiz.id)
        elif action == 'publish':
            active_bank = quiz.questions.filter(is_active=True, question_type__in=ALLOWED_TYPES)
            priority_count = active_bank.filter(order__lt=QUESTION_BANK_ARCHIVE_OFFSET).count()
            historical_count = active_bank.filter(order__gte=QUESTION_BANK_ARCHIVE_OFFSET).count()
            if priority_count == 0 and historical_count:
                priority_count, historical_count = historical_count, 0
            available_count = priority_count + historical_count if quiz.randomize_questions else priority_count
            if available_count < quiz.question_count:
                if quiz.randomize_questions:
                    detail = f'El XLSX prioritario y el banco histórico de este módulo suman {available_count} preguntas.'
                else:
                    detail = f'El XLSX prioritario de este módulo tiene {available_count} preguntas y el banco automático está desactivado.'
                messages.error(request, f'{detail} La evaluación necesita al menos {quiz.question_count}.')
            else:
                quiz.is_active = True
                quiz.save(update_fields=['is_active'])
                messages.success(request, 'Evaluación publicada. Las preguntas se tomarán únicamente del banco de este módulo.')
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
                messages.success(request, f'{count} preguntas importadas. Este XLSX queda como prioridad y el banco anterior de este módulo queda disponible como respaldo automático.')
                for error in errors[:10]:
                    messages.warning(request, error)
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

    current_questions = quiz.questions.filter(
        question_type__in=ALLOWED_TYPES, is_active=True
    ).prefetch_related('choices').order_by('order', 'id')
    priority_questions = current_questions.filter(order__lt=QUESTION_BANK_ARCHIVE_OFFSET)
    historical_questions = current_questions.filter(order__gte=QUESTION_BANK_ARCHIVE_OFFSET)
    priority_count = priority_questions.count()
    historical_count = historical_questions.count()
    if priority_count == 0 and historical_count:
        # Compatibilidad con bancos creados antes de separar lote prioritario/histórico.
        priority_questions = current_questions
        historical_questions = current_questions.none()
        priority_count = historical_count
        historical_count = 0

    bank_scope_label = quiz.module.title if quiz.module else 'Examen final del curso'
    available_count = priority_count + historical_count if quiz.randomize_questions else priority_count
    return render(request, 'professor/import_questions.html', {
        'form': form,
        'settings_form': settings_form,
        'quiz': quiz,
        'preview_rows': preview_rows,
        'preview_errors': preview_errors,
        'current_questions': current_questions,
        'priority_questions': priority_questions,
        'historical_questions': historical_questions,
        'priority_count': priority_count,
        'historical_count': historical_count,
        'available_count': available_count,
        'bank_scope_label': bank_scope_label,
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
