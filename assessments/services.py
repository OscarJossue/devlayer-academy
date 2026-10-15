import random
import re
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from .models import AttemptAnswer, Choice, Question, QuizAttempt, QuizEnrollmentOverride

OPEN_TYPE = 'OPEN'
PENDING_PREFIX = '__RESPUESTA__PENDIENTE__:'
REVIEWED_PREFIX = '__RESPUESTA__REVISADA__'
REVIEWED_RE = re.compile(r'^__RESPUESTA__REVISADA__(\d+(?:\.\d+)?)__:(.*)$', re.S)


def can_start_attempt(quiz, enrollment):
    if not enrollment.access_allowed() or enrollment.course_id != quiz.course_id or not quiz.is_active:
        return False, 'No tienes acceso a esta evaluación.'
    if quiz.kind == quiz.Kind.MODULE and quiz.module:
        pending = quiz.module.lessons.filter(is_published=True).exclude(progress_records__enrollment=enrollment, progress_records__completed_at__isnull=False)
        if pending.exists():
            return False, 'Completa las clases del módulo antes del cuestionario.'
    if quiz.kind == quiz.Kind.FINAL:
        from catalog.models import Lesson
        pending = Lesson.objects.filter(module__course=quiz.course, is_published=True).exclude(progress_records__enrollment=enrollment, progress_records__completed_at__isnull=False)
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


def get_or_create_attempt(quiz, enrollment):
    existing = quiz.attempts.filter(enrollment=enrollment, submitted_at__isnull=True).first()
    if existing:
        return existing
    ok, error = can_start_attempt(quiz, enrollment)
    if not ok:
        raise PermissionError(error)
    qs = list(quiz.questions.filter(is_active=True).values_list('id', flat=True))
    if quiz.randomize_questions:
        random.shuffle(qs)
    question_ids = [str(x) for x in qs[:quiz.question_count]]
    number = quiz.attempts.filter(enrollment=enrollment).count() + 1
    return QuizAttempt.objects.create(quiz=quiz, enrollment=enrollment, number=number, question_ids=question_ids)


def _required_score(attempt):
    override = QuizEnrollmentOverride.objects.filter(quiz=attempt.quiz, enrollment=attempt.enrollment).first()
    return override.pass_percentage_override if override and override.pass_percentage_override else attempt.quiz.required_score


def _open_choice(answer):
    return answer.selected_choices.filter(text__startswith='__RESPUESTA__').first()


def open_answer_data(answer):
    choice = _open_choice(answer)
    if not choice:
        return {'text': '', 'pending': True, 'score': None}
    text = choice.text
    if text.startswith(PENDING_PREFIX):
        return {'text': text[len(PENDING_PREFIX):], 'pending': True, 'score': None}
    match = REVIEWED_RE.match(text)
    if match:
        return {'text': match.group(2), 'pending': False, 'score': Decimal(match.group(1))}
    return {'text': text, 'pending': True, 'score': None}


def attempt_needs_review(attempt):
    for answer in attempt.answers.select_related('question').prefetch_related('selected_choices').all():
        if answer.question.question_type == OPEN_TYPE and open_answer_data(answer)['pending']:
            return True
    return False


@transaction.atomic
def submit_attempt(attempt, post_data):
    if attempt.submitted_at:
        return attempt
    questions = list(Question.objects.filter(id__in=attempt.question_ids).prefetch_related('choices'))
    score_values = []
    has_open = False
    for question in questions:
        if question.question_type == OPEN_TYPE:
            has_open = True
            text = (post_data.get(f'q_{question.id}') or '').strip()[:450]
            answer = AttemptAnswer.objects.create(attempt=attempt, question=question, is_correct=False)
            temp_choice = Choice.objects.create(
                question=question,
                text=f'{PENDING_PREFIX}{text}',
                is_correct=False,
                order=9999,
            )
            answer.selected_choices.add(temp_choice)
            continue
        selected_ids = post_data.getlist(f'q_{question.id}')
        selected = list(Choice.objects.filter(question=question, id__in=selected_ids))
        correct_ids = set(str(x) for x in question.choices.filter(is_correct=True).values_list('id', flat=True))
        selected_set = set(str(x.id) for x in selected)
        is_correct = bool(correct_ids) and selected_set == correct_ids
        answer = AttemptAnswer.objects.create(attempt=attempt, question=question, is_correct=is_correct)
        answer.selected_choices.set(selected)
        score_values.append(Decimal('100') if is_correct else Decimal('0'))
    attempt.submitted_at = timezone.now()
    if has_open:
        attempt.score = None
        attempt.passed = False
    else:
        score = sum(score_values, Decimal('0')) / Decimal(len(score_values) or 1)
        attempt.score = round(score, 2)
        attempt.passed = attempt.score >= _required_score(attempt)
    attempt.save(update_fields=['score', 'passed', 'submitted_at'])
    if attempt.passed:
        from certificates.services import issue_certificate_if_eligible
        issue_certificate_if_eligible(attempt.enrollment)
    return attempt


@transaction.atomic
def review_open_attempt(attempt, scores):
    answers = list(attempt.answers.select_related('question').prefetch_related('selected_choices').all())
    values = []
    for answer in answers:
        if answer.question.question_type == OPEN_TYPE:
            data = open_answer_data(answer)
            raw = scores.get(str(answer.id), 0)
            try:
                value = max(Decimal('0'), min(Decimal('100'), Decimal(str(raw))))
            except Exception:
                value = Decimal('0')
            choice = _open_choice(answer)
            if choice:
                choice.text = f'{REVIEWED_PREFIX}{value}__:{data["text"]}'
                choice.is_correct = value >= Decimal('70')
                choice.save(update_fields=['text', 'is_correct'])
            answer.is_correct = value >= Decimal('70')
            answer.save(update_fields=['is_correct'])
            values.append(value)
        else:
            values.append(Decimal('100') if answer.is_correct else Decimal('0'))
    attempt.score = round(sum(values, Decimal('0')) / Decimal(len(values) or 1), 2)
    attempt.passed = attempt.score >= _required_score(attempt)
    attempt.save(update_fields=['score', 'passed'])
    if attempt.passed:
        from certificates.services import issue_certificate_if_eligible
        issue_certificate_if_eligible(attempt.enrollment)
    return attempt
