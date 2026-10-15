from django.utils import timezone
from catalog.models import Lesson
from .models import Enrollment, LessonProgress


def create_or_activate_enrollment(user, course, source=Enrollment.Source.MANUAL):
    enrollment, created = Enrollment.objects.get_or_create(user=user, course=course, defaults={'source': source, 'status': Enrollment.Status.ACTIVE})
    if created:
        enrollment.configure_default_expiry()
        enrollment.save(update_fields=['expires_at'])
    else:
        if enrollment.status in {Enrollment.Status.BLOCKED, Enrollment.Status.EXPIRED, Enrollment.Status.REVOKED}:
            enrollment.status = Enrollment.Status.ACTIVE
            enrollment.blocked_reason = ''
            if enrollment.expires_at and enrollment.expires_at < timezone.now():
                enrollment.starts_at = timezone.now()
                enrollment.configure_default_expiry()
            enrollment.save()
    return enrollment


def get_enrollment_or_none(user, course):
    if not getattr(user, 'is_authenticated', False):
        return None
    return Enrollment.objects.filter(user=user, course=course).first()


def can_access_lesson(enrollment, lesson):
    if not enrollment or enrollment.course_id != lesson.module.course_id or not enrollment.access_allowed():
        return False
    if not enrollment.course.sequential_learning:
        return True
    # Las previsualizaciones siempre son visibles para usuarios matriculados.
    if lesson.is_preview:
        return True
    previous_in_module = Lesson.objects.filter(module=lesson.module, order__lt=lesson.order, is_published=True)
    if previous_in_module.exclude(progress_records__enrollment=enrollment, progress_records__completed_at__isnull=False).exists():
        return False
    # Para módulos posteriores, todas las clases anteriores deben completarse y los quizzes requeridos aprobarse.
    previous_modules = enrollment.course.modules.filter(order__lt=lesson.module.order, is_published=True)
    previous_lessons = Lesson.objects.filter(module__in=previous_modules, is_published=True)
    if previous_lessons.exclude(progress_records__enrollment=enrollment, progress_records__completed_at__isnull=False).exists():
        return False
    from assessments.models import Quiz
    required_quizzes = Quiz.objects.filter(module__in=previous_modules, is_required=True, is_active=True)
    for quiz in required_quizzes:
        if not quiz.attempts.filter(enrollment=enrollment, passed=True).exists():
            return False
    return True


def progress_percentage(enrollment):
    from assessments.models import Quiz
    lessons = Lesson.objects.filter(module__course=enrollment.course, is_published=True)
    required_quizzes = Quiz.objects.filter(course=enrollment.course, is_required=True, is_active=True)
    total = lessons.count() + required_quizzes.count()
    if total == 0:
        return 0
    completed_lessons = LessonProgress.objects.filter(enrollment=enrollment, lesson__in=lessons, completed_at__isnull=False).count()
    passed_quizzes = sum(1 for q in required_quizzes if q.attempts.filter(enrollment=enrollment, passed=True).exists())
    return round(((completed_lessons + passed_quizzes) / total) * 100)


def mark_lesson_complete(enrollment, lesson):
    progress, _ = LessonProgress.objects.get_or_create(enrollment=enrollment, lesson=lesson)
    if not progress.completed_at:
        progress.completed_at = timezone.now()
        progress.save(update_fields=['completed_at', 'last_viewed_at'])
    from certificates.services import issue_certificate_if_eligible
    issue_certificate_if_eligible(enrollment)
    return progress
