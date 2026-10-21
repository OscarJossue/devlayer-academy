import random
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import AttemptAnswer, Choice, Question, QuizAttempt, QuizEnrollmentOverride

ALLOWED_TYPES = {Question.Type.SINGLE, Question.Type.MULTIPLE}


def can_start_attempt(quiz, enrollment):
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
        pending = Lesson.objects.filter(module__course=quiz.course, is_published=True).exclude(
            progress_records__enrollment=enrollment,
            progress_records__completed_at__isnull=False,
        )
        if pending.exists():
            return False, 'Completa el contenido antes del examen final.'
    submitted_count = quiz.attempts.filter(enrollment=enrollment, submitted_at__isnull=False).count()
    override = QuizEnrollmentOverride.objects.filter(quiz=quiz, enrollment=enrollment).first()
    base_max = quiz.max_attempts
    if override and override.max_attempts_override is not None:
        base_max = override.max_attempts_override
    effective_max = 0 if base_max == 0 else base_max + (override.extra_attempts if override else 0)
    if effective_max and submitted_count >= effective_max:
        return False, 'Ya utilizaste todos los intentos disponibles.'
    return True, ''


def _eligible_question_ids(quiz):
    return list(
        quiz.questions.filter(is_active=True, question_type__in=ALLOWED_TYPES)
        .order_by('order', 'id')
        .values_list('id', flat=True)
    )


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
            if quiz.randomize_questions:
                random.shuffle(selected)
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
    if quiz.randomize_questions:
        random.shuffle(eligible)
    question_ids = [str(x) for x in eligible[:quiz.question_count]]
    number = quiz.attempts.filter(enrollment=enrollment).count() + 1
    return QuizAttempt.objects.create(
        quiz=quiz,
        enrollment=enrollment,
        number=number,
        question_ids=question_ids,
    )


def _required_score(attempt):
    override = QuizEnrollmentOverride.objects.filter(quiz=attempt.quiz, enrollment=attempt.enrollment).first()
    return override.pass_percentage_override if override and override.pass_percentage_override else attempt.quiz.required_score


def attempt_needs_review(attempt):
    """Las evaluaciones nuevas se califican automáticamente; se conserva por compatibilidad."""
    return False


@transaction.atomic
def submit_attempt(attempt, post_data):
    if attempt.submitted_at:
        return attempt

    questions = list(
        Question.objects.filter(id__in=attempt.question_ids, question_type__in=ALLOWED_TYPES)
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

    attempt.submitted_at = timezone.now()
    score = sum(score_values, Decimal('0')) / Decimal(len(score_values) or 1)
    attempt.score = round(score, 2)
    attempt.passed = attempt.score >= _required_score(attempt)
    attempt.save(update_fields=['score', 'passed', 'submitted_at'])

    if attempt.passed:
        from certificates.services import issue_certificate_if_eligible
        issue_certificate_if_eligible(attempt.enrollment)
    return attempt
