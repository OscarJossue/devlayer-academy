from django.db import transaction
from django.conf import settings
from django.utils import timezone

from assessments.models import Quiz
from assessments.services import valid_quizzes_for_course
from catalog.models import Lesson
from tenancy.mail import academy_mail_available, send_academy_mail
from tenancy.services import academy_for_course
from .models import Certificate


def _completion_requirements_met(enrollment):
    course = enrollment.course
    lessons = Lesson.objects.filter(module__course=course, is_published=True)
    if lessons.exclude(progress_records__enrollment=enrollment, progress_records__completed_at__isnull=False).exists():
        return False
    required = valid_quizzes_for_course(course).filter(is_required=True, is_active=True)
    for quiz in required:
        if not quiz.attempts.filter(enrollment=enrollment, passed=True).exists():
            return False
    if course.final_exam_required:
        finals = valid_quizzes_for_course(course).filter(kind=Quiz.Kind.FINAL, is_required=True, is_active=True)
        if not finals.exists() or any(not q.attempts.filter(enrollment=enrollment, passed=True).exists() for q in finals):
            return False
    return True


@transaction.atomic
def issue_certificate_if_eligible(enrollment):
    """Cierra el curso al cumplir requisitos y emite certificado solo si el curso lo habilita."""
    if hasattr(enrollment, 'certificate'):
        return enrollment.certificate
    course = enrollment.course
    if not _completion_requirements_met(enrollment):
        return None

    # Cursos sin certificado siguen pudiendo finalizarse al 100 %.
    if not course.certificate_enabled:
        if enrollment.status != enrollment.Status.COMPLETED:
            enrollment.status = enrollment.Status.COMPLETED
            enrollment.save(update_fields=['status', 'updated_at'])
        return None

    certificate = Certificate.objects.create(enrollment=enrollment)
    enrollment.certified_at = certificate.issued_at or timezone.now()
    enrollment.status = enrollment.Status.COMPLETED
    enrollment.save(update_fields=['certified_at', 'status', 'updated_at'])

    academy = academy_for_course(course)
    academy_name = academy.name if academy else 'Academia'
    if academy and academy_mail_available(academy):
        base = settings.PUBLIC_BASE_URL.rstrip('/')
        verify_url = f'{base}/certificados/verificar/{certificate.code}/'
        pdf_url = f'{base}/certificados/{certificate.code}/pdf/'
        send_academy_mail(
            academy,
            subject=f'Certificado disponible · {course.title}',
            message=(
                f'Hola {enrollment.user.display_name},\n\n'
                f'Completaste satisfactoriamente “{course.title}”. Tu certificado ya está disponible.\n\n'
                f'Código: {certificate.code}\nDescargar certificado: {pdf_url}\nValidación pública: {verify_url}\n\n'
                f'Felicitaciones por completar tu ruta de aprendizaje.\n{academy_name}'
            ),
            recipients=[enrollment.user.email],
            fail_silently=True,
            html_message=(
                f'<div style="font-family:Arial,sans-serif;color:#172033">'
                f'<img src="cid:academy-logo" alt="{academy_name}" style="display:block;max-width:180px;max-height:64px;object-fit:contain;margin-bottom:22px">'
                f'<h2>Certificado disponible</h2>'
                f'<p>Hola <strong>{enrollment.user.display_name}</strong>.</p>'
                f'<p>Completaste satisfactoriamente <strong>{course.title}</strong>.</p>'
                f'<p><a href="{pdf_url}">Descargar certificado</a> · '
                f'<a href="{verify_url}">Verificar certificado</a></p></div>'
            ),
            attach_brand_logo=True,
        )
    return certificate
