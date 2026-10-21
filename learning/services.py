from django.utils import timezone
from catalog.models import Lesson
from tenancy.models import AcademyMembership
from tenancy.services import academy_for_course, membership_for_user
from .models import Enrollment, LessonProgress


def create_or_activate_enrollment(user, course, source=Enrollment.Source.MANUAL):
    course_academy = academy_for_course(course)
    membership = membership_for_user(user, academy=course_academy) if course_academy else None
    if not course_academy or not membership or membership.status != AcademyMembership.Status.ACTIVE:
        raise PermissionError('El usuario no tiene una membresía activa en la academia de este curso.')
    if not course_academy.access_enabled:
        raise PermissionError('La licencia de la academia no está activa.')
    enrollment, created = Enrollment.objects.get_or_create(user=user, course=course, defaults={'source': source, 'status': Enrollment.Status.ACTIVE})
    if created:
        enrollment.configure_default_expiry(); enrollment.save(update_fields=['expires_at'])
    elif enrollment.status in {Enrollment.Status.BLOCKED, Enrollment.Status.EXPIRED, Enrollment.Status.REVOKED}:
        enrollment.status = Enrollment.Status.ACTIVE; enrollment.blocked_reason = ''
        if enrollment.expires_at and enrollment.expires_at < timezone.now():
            enrollment.starts_at = timezone.now(); enrollment.configure_default_expiry()
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
    if lesson.is_preview:
        return True
    previous_in_module = Lesson.objects.filter(module=lesson.module, order__lt=lesson.order, is_published=True)
    if previous_in_module.exclude(progress_records__enrollment=enrollment, progress_records__completed_at__isnull=False).exists():
        return False
    previous_modules = enrollment.course.modules.filter(order__lt=lesson.module.order, is_published=True)
    previous_lessons = Lesson.objects.filter(module__in=previous_modules, is_published=True)
    if previous_lessons.exclude(progress_records__enrollment=enrollment, progress_records__completed_at__isnull=False).exists():
        return False
    from assessments.models import Quiz
    for quiz in Quiz.objects.filter(module__in=previous_modules, is_required=True, is_active=True):
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
        progress.completed_at = timezone.now(); progress.save(update_fields=['completed_at', 'last_viewed_at'])
    from certificates.services import issue_certificate_if_eligible
    issue_certificate_if_eligible(enrollment)
    return progress


def _ordered_lessons(course):
    return list(
        Lesson.objects.filter(module__course=course, is_published=True, module__is_published=True)
        .select_related('module')
        .order_by('module__order', 'order', 'id')
    )


def _quiz_passed(quiz, enrollment):
    return quiz.attempts.filter(enrollment=enrollment, passed=True).exists()


def resume_learning_target(enrollment):
    """Devuelve el siguiente paso real del estudiante.

    Corrige el bug histórico donde “Continuar curso” siempre regresaba a la
    primera clase accesible, aunque ya estuviera completada.
    """
    from assessments.models import Quiz

    course = enrollment.course
    completed = set(
        LessonProgress.objects.filter(enrollment=enrollment, completed_at__isnull=False)
        .values_list('lesson_id', flat=True)
    )

    for module in course.modules.filter(is_published=True).order_by('order', 'id'):
        lessons = list(module.lessons.filter(is_published=True).order_by('order', 'id'))
        for lesson in lessons:
            if lesson.id not in completed:
                if can_access_lesson(enrollment, lesson):
                    return {'kind': 'lesson', 'lesson': lesson}
                break
        else:
            for pending_quiz in Quiz.objects.filter(module=module, is_required=True, is_active=True).order_by('created_at'):
                if not _quiz_passed(pending_quiz, enrollment):
                    return {'kind': 'quiz', 'quiz': pending_quiz}

    for final_quiz in Quiz.objects.filter(course=course, module__isnull=True, kind=Quiz.Kind.FINAL, is_required=True, is_active=True).order_by('created_at'):
        if not _quiz_passed(final_quiz, enrollment):
            return {'kind': 'quiz', 'quiz': final_quiz}
    return None


def next_step_after_lesson(enrollment, lesson):
    """Calcula el destino del botón de avance situado debajo del video."""
    from assessments.models import Quiz

    course = enrollment.course
    module = lesson.module
    later_in_module = module.lessons.filter(is_published=True, order__gt=lesson.order).order_by('order', 'id').first()
    if later_in_module:
        return {'kind': 'lesson', 'lesson': later_in_module, 'label': 'Siguiente clase'}

    for module_quiz in Quiz.objects.filter(module=module, is_required=True, is_active=True).order_by('created_at'):
        if not _quiz_passed(module_quiz, enrollment):
            return {'kind': 'quiz', 'quiz': module_quiz, 'label': 'Continuar al cuestionario'}

    next_module = course.modules.filter(is_published=True, order__gt=module.order).order_by('order', 'id').first()
    if next_module:
        next_lesson = next_module.lessons.filter(is_published=True).order_by('order', 'id').first()
        if next_lesson:
            return {'kind': 'lesson', 'lesson': next_lesson, 'label': 'Siguiente módulo'}

    for final_quiz in Quiz.objects.filter(course=course, module__isnull=True, kind=Quiz.Kind.FINAL, is_required=True, is_active=True).order_by('created_at'):
        if not _quiz_passed(final_quiz, enrollment):
            return {'kind': 'quiz', 'quiz': final_quiz, 'label': 'Ir al examen final'}
    return {'kind': 'done', 'label': 'Finalizar curso'}


def previous_lesson_for(course, lesson):
    lessons = _ordered_lessons(course)
    for index, current in enumerate(lessons):
        if current.id == lesson.id:
            return lessons[index - 1] if index > 0 else None
    return None


def course_navigation_context(enrollment, *, active_lesson_id=None, active_quiz_id=None, active_masterclass=False):
    """Contexto compartido para mantener visible la navegación del curso.

    Los cuestionarios nunca sustituyen ni ocultan la teoría: el alumno puede
    volver a cualquier clase ya desbloqueada mientras realiza una evaluación.
    """
    from assessments.models import Quiz

    course = enrollment.course
    completed_ids = set(
        LessonProgress.objects.filter(enrollment=enrollment, completed_at__isnull=False)
        .values_list('lesson_id', flat=True)
    )
    modules = list(
        course.modules.filter(is_published=True)
        .prefetch_related('lessons', 'quizzes')
        .order_by('order', 'id')
    )
    for module in modules:
        nav_lessons = [item for item in module.lessons.all() if item.is_published]
        nav_lessons.sort(key=lambda item: (item.order, str(item.id)))
        for item in nav_lessons:
            item.student_completed = item.id in completed_ids
            item.student_can_open = can_access_lesson(enrollment, item)
        module.nav_lessons = nav_lessons

        nav_quizzes = [item for item in module.quizzes.all() if item.is_active]
        nav_quizzes.sort(key=lambda item: (item.created_at, str(item.id)))
        for quiz in nav_quizzes:
            quiz.student_passed = quiz.attempts.filter(enrollment=enrollment, passed=True).exists()
        module.nav_quizzes = nav_quizzes

    final_quizzes = list(
        Quiz.objects.filter(
            course=course,
            module__isnull=True,
            kind=Quiz.Kind.FINAL,
            is_active=True,
        ).order_by('created_at', 'id')
    )
    for quiz in final_quizzes:
        quiz.student_passed = quiz.attempts.filter(enrollment=enrollment, passed=True).exists()

    return {
        # El sidebar se reutiliza también desde cuestionarios/resultados.
        # Esas vistas no siempre agregan `course` manualmente al contexto,
        # por eso debe viajar dentro del contexto de navegación compartido.
        'course': course,
        'enrollment': enrollment,
        'course_nav_modules': modules,
        'course_nav_final_quizzes': final_quizzes,
        'course_progress_percentage': progress_percentage(enrollment),
        'active_lesson_id': active_lesson_id,
        'active_quiz_id': active_quiz_id,
        'active_masterclass': active_masterclass,
    }
