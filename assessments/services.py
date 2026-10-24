import random
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import AttemptAnswer, Choice, Question, Quiz, QuizAttempt, QuizEnrollmentOverride
from .importers import QUESTION_BANK_ARCHIVE_OFFSET

ALLOWED_TYPES = {Question.Type.SINGLE, Question.Type.MULTIPLE}

HARD_TIMER_GRACE_SECONDS = 20


def valid_quizzes_for_course(course):
    """Única fuente de verdad para evaluaciones académicamente válidas del curso.

    - Cuestionarios de módulo: el módulo debe pertenecer al mismo curso.
    - Examen final: no puede estar ligado a ningún módulo.
    """
    return Quiz.objects.filter(course=course).filter(
        Q(kind=Quiz.Kind.FINAL, module__isnull=True)
        | Q(kind=Quiz.Kind.MODULE, module__course=course)
    )


def quiz_scope_is_valid(quiz):
    if quiz.kind == Quiz.Kind.FINAL:
        return quiz.module_id is None
    return bool(quiz.module_id and quiz.module.course_id == quiz.course_id)


def _seconds_label(total_seconds):
    total = max(int(total_seconds or 0), 0)
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f'{hours} h {minutes:02d} min {seconds:02d} s'
    if minutes:
        return f'{minutes} min {seconds:02d} s'
    return f'{seconds} s'


def attempt_timing(attempt, now=None):
    now = now or timezone.now()
    mode = attempt.time_mode_snapshot or Quiz.TimeMode.NONE
    limit_minutes = attempt.time_limit_minutes_snapshot or 0
    limit_seconds = int(limit_minutes * 60)
    end = attempt.submitted_at or now
    elapsed = max(int((end - attempt.started_at).total_seconds()), 0)
    remaining = max(limit_seconds - elapsed, 0) if limit_seconds else 0
    overtime = max(elapsed - limit_seconds, 0) if limit_seconds else 0
    hard_expired = bool(mode == Quiz.TimeMode.LIMIT and limit_seconds and elapsed > limit_seconds)
    return {
        'mode': mode,
        'limit_minutes': limit_minutes,
        'limit_seconds': limit_seconds,
        'elapsed_seconds': elapsed,
        'remaining_seconds': remaining,
        'overtime_seconds': overtime,
        'hard_expired': hard_expired,
        'elapsed_label': _seconds_label(elapsed),
        'remaining_label': _seconds_label(remaining),
        'overtime_label': _seconds_label(overtime),
    }


def can_start_attempt(quiz, enrollment):
    if not quiz_scope_is_valid(quiz):
        return False, 'La evaluación no está vinculada correctamente a su curso o módulo.'
    if not enrollment.access_allowed() or enrollment.course_id != quiz.course_id or not quiz.is_active:
        return False, 'No tienes acceso a esta evaluación.'
    if quiz.kind == quiz.Kind.MODULE and quiz.module:
        pending = quiz.module.lessons.filter(is_published=True).exclude(
            progress_records__enrollment=enrollment,
            progress_records__completed_at__isnull=False,
        )
        if pending.exists():
            return False, 'Completa las clases del módulo antes del cuestionario.'
    if quiz.kind == quiz.Kind.FINAL:
        from catalog.models import Lesson
        from .models import Quiz

        pending = Lesson.objects.filter(
            module__course=quiz.course,
            module__is_published=True,
            is_published=True,
        ).exclude(
            progress_records__enrollment=enrollment,
            progress_records__completed_at__isnull=False,
        )
        if pending.exists():
            return False, 'Completa todas las clases antes de habilitar el examen final.'

        required_previous = valid_quizzes_for_course(quiz.course).filter(
            kind=Quiz.Kind.MODULE,
            is_required=True,
            is_active=True,
        ).exclude(pk=quiz.pk)
        for previous_quiz in required_previous:
            if not previous_quiz.attempts.filter(enrollment=enrollment, passed=True).exists():
                return False, 'Aprueba todos los cuestionarios anteriores antes de habilitar el examen final.'
    submitted_count = quiz.attempts.filter(enrollment=enrollment, submitted_at__isnull=False).count()
    override = QuizEnrollmentOverride.objects.filter(quiz=quiz, enrollment=enrollment).first()
    base_max = quiz.max_attempts
    if override and override.max_attempts_override is not None:
        base_max = override.max_attempts_override
    effective_max = 0 if base_max == 0 else base_max + (override.extra_attempts if override else 0)
    if effective_max and submitted_count >= effective_max:
        return False, 'Ya utilizaste todos los intentos disponibles.'
    return True, ''


def _question_pools(quiz):
    """Devuelve lote XLSX prioritario + banco histórico del MISMO quiz.

    `quiz.randomize_questions` se usa como el interruptor de UX
    "Completar automáticamente con el banco de este módulo". Nunca se consulta
    otro quiz, módulo o curso.
    """
    base = quiz.questions.filter(is_active=True, question_type__in=ALLOWED_TYPES)
    primary = list(
        base.filter(order__lt=QUESTION_BANK_ARCHIVE_OFFSET)
        .order_by('order', 'id')
        .values_list('id', flat=True)
    )
    historical = list(
        base.filter(order__gte=QUESTION_BANK_ARCHIVE_OFFSET)
        .order_by('order', 'id')
        .values_list('id', flat=True)
    )

    # Compatibilidad con bancos existentes creados antes de esta mejora: si no
    # existe un lote marcado como histórico, todo el banco actual es prioritario.
    if not primary and historical:
        primary, historical = historical, []
    return primary, historical


def _eligible_question_ids(quiz):
    primary, historical = _question_pools(quiz)
    if quiz.randomize_questions:
        random.shuffle(primary)
        random.shuffle(historical)
        return primary + historical
    return primary


def get_or_create_attempt(quiz, enrollment):
    existing = quiz.attempts.filter(enrollment=enrollment, submitted_at__isnull=True).first()
    eligible = _eligible_question_ids(quiz)
    if existing:
        eligible_set = {str(value) for value in eligible}
        cleaned = [qid for qid in existing.question_ids if qid in eligible_set]
        if len(cleaned) < quiz.question_count:
            if len(eligible) < quiz.question_count:
                raise PermissionError(
                    f'Esta evaluación necesita {quiz.question_count} preguntas automáticas, pero solo tiene {len(eligible)} disponibles.'
                )
            selected = eligible[:]
            cleaned = [str(x) for x in selected[:quiz.question_count]]
        if cleaned != existing.question_ids:
            existing.question_ids = cleaned
            existing.save(update_fields=['question_ids'])
        return existing

    ok, error = can_start_attempt(quiz, enrollment)
    if not ok:
        raise PermissionError(error)
    if len(eligible) < quiz.question_count:
        raise PermissionError(
            f'Esta evaluación necesita {quiz.question_count} preguntas automáticas, pero solo tiene {len(eligible)} disponibles.'
        )
    question_ids = [str(x) for x in eligible[:quiz.question_count]]
    number = quiz.attempts.filter(enrollment=enrollment).count() + 1
    return QuizAttempt.objects.create(
        quiz=quiz,
        enrollment=enrollment,
        number=number,
        question_ids=question_ids,
        time_mode_snapshot=quiz.time_mode,
        time_limit_minutes_snapshot=quiz.time_limit_minutes,
    )


def _required_score(attempt):
    override = QuizEnrollmentOverride.objects.filter(quiz=attempt.quiz, enrollment=attempt.enrollment).first()
    return override.pass_percentage_override if override and override.pass_percentage_override else attempt.quiz.required_score


def attempt_needs_review(attempt):
    """Las evaluaciones nuevas se califican automáticamente; se conserva por compatibilidad."""
    return False


@transaction.atomic
def submit_attempt(attempt, post_data, *, timed_out=False):
    if attempt.submitted_at:
        return attempt

    questions = list(
        Question.objects.filter(id__in=attempt.question_ids, quiz=attempt.quiz, question_type__in=ALLOWED_TYPES)
        .prefetch_related('choices')
    )
    ordered = {str(question.id): question for question in questions}
    questions = [ordered[qid] for qid in attempt.question_ids if qid in ordered]
    score_values = []

    for question in questions:
        selected_ids = post_data.getlist(f'q_{question.id}')
        selected = list(Choice.objects.filter(question=question, id__in=selected_ids))
        correct_ids = set(str(x) for x in question.choices.filter(is_correct=True).values_list('id', flat=True))
        selected_set = set(str(x.id) for x in selected)
        is_correct = bool(correct_ids) and selected_set == correct_ids
        answer = AttemptAnswer.objects.create(attempt=attempt, question=question, is_correct=is_correct)
        answer.selected_choices.set(selected)
        score_values.append(Decimal('100') if is_correct else Decimal('0'))

    submitted_at = timezone.now()
    attempt.submitted_at = submitted_at
    timing = attempt_timing(attempt, now=submitted_at)
    attempt.elapsed_seconds = timing['elapsed_seconds']
    attempt.overtime_seconds = timing['overtime_seconds'] if attempt.time_mode_snapshot == Quiz.TimeMode.STOPWATCH else 0
    attempt.timed_out = bool(timed_out or (attempt.time_mode_snapshot == Quiz.TimeMode.LIMIT and timing['hard_expired']))
    score = sum(score_values, Decimal('0')) / Decimal(len(score_values) or 1)
    attempt.score = round(score, 2)
    attempt.passed = attempt.score >= _required_score(attempt)
    attempt.save(update_fields=['score', 'passed', 'submitted_at', 'elapsed_seconds', 'overtime_seconds', 'timed_out'])

    if attempt.passed:
        from certificates.services import issue_certificate_if_eligible
        issue_certificate_if_eligible(attempt.enrollment)
    return attempt
