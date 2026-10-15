import random

from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from core.decorators import professor_required, verified_email_required
from catalog.models import Course
from learning.models import Enrollment
from .forms import QuizForm, QuestionImportForm
from .importers import import_question_rows, read_question_xlsx, reuse_questions
from .models import Question, Quiz, QuizAttempt
from .services import attempt_needs_review, get_or_create_attempt, open_answer_data, review_open_attempt, submit_attempt


@verified_email_required
def quiz_take(request, quiz_id):
    quiz = get_object_or_404(Quiz.objects.select_related('course', 'module'), id=quiz_id, is_active=True)
    enrollment = get_object_or_404(Enrollment, user=request.user, course=quiz.course)
    try:
        attempt = get_or_create_attempt(quiz, enrollment)
    except PermissionError as exc:
        messages.error(request, str(exc))
        return redirect('learning:course_player', course_slug=quiz.course.slug)
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
        if attempt_needs_review(attempt):
            messages.success(request, 'Evaluación enviada. Las preguntas abiertas quedaron pendientes de revisión del profesor.')
        else:
            messages.success(request, f'Evaluación enviada. Nota: {attempt.score}%')
        return redirect('assessments:result', attempt.id)
    questions = list(Question.objects.filter(id__in=attempt.question_ids).prefetch_related('choices'))
    ordered = {str(q.id): q for q in questions}
    questions = [ordered[qid] for qid in attempt.question_ids if qid in ordered]
    question_data = []
    for q in questions:
        choices = list(q.choices.all())
        if quiz.randomize_choices:
            random.shuffle(choices)
        question_data.append((q, choices))
    return render(request, 'assessments/take.html', {'quiz': quiz, 'attempt': attempt, 'question_data': question_data, 'require_identity': require_identity})


@verified_email_required
def result(request, attempt_id):
    attempt = get_object_or_404(QuizAttempt.objects.select_related('quiz', 'enrollment__user'), id=attempt_id, enrollment__user=request.user)
    return render(request, 'assessments/result.html', {'attempt': attempt, 'needs_review': attempt_needs_review(attempt)})


def _own_course(user, course_id):
    qs = Course.objects.all()
    if not user.is_superuser:
        qs = qs.filter(instructor_links__user=user)
    return get_object_or_404(qs.distinct(), id=course_id)


@professor_required
def quiz_create(request, course_id):
    course = _own_course(request.user, course_id)
    form = QuizForm(request.POST or None)
    form.fields['module'].queryset = course.modules.all()
    if request.method == 'POST' and form.is_valid():
        quiz = form.save(commit=False)
        quiz.course = course
        quiz.is_active = False
        if quiz.kind == Quiz.Kind.FINAL:
            quiz.module = None
        quiz.save()
        messages.success(request, 'Evaluación creada. Antes de usarla, carga o reutiliza preguntas y revisa la vista previa.')
        return redirect('assessments:professor_import_questions', quiz.id)
    return render(request, 'professor/simple_form.html', {'form': form, 'title': f'Nueva evaluación · {course.title}', 'helper': 'Configura preguntas, nota mínima, intentos y aleatoriedad. Usa 0 intentos para permitir intentos ilimitados.', 'back_url': course.id})


@professor_required
def import_questions_view(request, quiz_id):
    quiz = get_object_or_404(Quiz.objects.select_related('course'), id=quiz_id)
    _own_course(request.user, quiz.course_id)
    session_key = f'preview_preguntas_{quiz.id}'
    preview_rows = request.session.get(session_key, [])
    preview_errors = []
    form = QuestionImportForm(request.POST or None, request.FILES or None)

    owned_courses = Course.objects.all() if request.user.is_superuser else Course.objects.filter(instructor_links__user=request.user)
    reusable = Question.objects.filter(quiz__course__in=owned_courses).exclude(quiz=quiz).select_related('quiz__course').prefetch_related('choices').order_by('-quiz__created_at', 'order')[:200]

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'publish':
            active_count = quiz.questions.filter(is_active=True).count()
            if active_count < quiz.question_count:
                messages.error(request, f'El banco tiene {active_count} preguntas activas y la evaluación necesita al menos {quiz.question_count}.')
            else:
                quiz.is_active = True
                quiz.save(update_fields=['is_active'])
                messages.success(request, 'Evaluación publicada. Ya está disponible para los estudiantes cuando corresponda por progreso.')
                return redirect('assessments:professor_import_questions', quiz.id)
        elif action == 'pause':
            quiz.is_active = False
            quiz.save(update_fields=['is_active'])
            messages.warning(request, 'Evaluación pausada. Los estudiantes no podrán iniciarla hasta que vuelvas a publicarla.')
            return redirect('assessments:professor_import_questions', quiz.id)
        elif action == 'confirm':
            if not preview_rows:
                messages.error(request, 'No hay preguntas previsualizadas para importar.')
            else:
                count, errors = import_question_rows(quiz, preview_rows)
                request.session.pop(session_key, None)
                messages.success(request, f'{count} preguntas importadas al banco.')
                for error in errors[:10]:
                    messages.warning(request, error)
                return redirect('assessments:professor_import_questions', quiz.id)
        elif action == 'reuse':
            selected = request.POST.getlist('question_ids')
            source_qs = reusable.filter(id__in=selected)
            count = reuse_questions(quiz, source_qs)
            messages.success(request, f'{count} preguntas reutilizadas en esta evaluación.')
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

    return render(request, 'professor/import_questions.html', {
        'form': form,
        'quiz': quiz,
        'preview_rows': preview_rows,
        'preview_errors': preview_errors,
        'reusable_questions': reusable,
        'current_questions': quiz.questions.prefetch_related('choices').all(),
    })


@professor_required
def review_attempt(request, attempt_id):
    attempt = get_object_or_404(QuizAttempt.objects.select_related('quiz__course', 'enrollment__user'), pk=attempt_id)
    _own_course(request.user, attempt.quiz.course_id)
    if request.method == 'POST':
        scores = {key.replace('score_', ''): value for key, value in request.POST.items() if key.startswith('score_')}
        review_open_attempt(attempt, scores)
        messages.success(request, f'Intento calificado. Nota final: {attempt.score}%.')
        return redirect('catalog:professor_students', attempt.quiz.course_id)
    answers = list(attempt.answers.select_related('question').prefetch_related('selected_choices').all())
    rows = []
    for answer in answers:
        rows.append({'answer': answer, 'open_data': open_answer_data(answer) if answer.question.question_type == 'OPEN' else None})
    return render(request, 'professor/review_attempt.html', {'attempt': attempt, 'answer_rows': rows})
