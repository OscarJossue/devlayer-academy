from django.db import transaction
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from assessments.models import Quiz
from catalog.models import Lesson
from learning.models import LessonProgress
from .models import Certificate

@transaction.atomic
def issue_certificate_if_eligible(enrollment):
    if hasattr(enrollment, 'certificate'):
        return enrollment.certificate
    course = enrollment.course
    lessons = Lesson.objects.filter(module__course=course, is_published=True)
    if lessons.exclude(progress_records__enrollment=enrollment, progress_records__completed_at__isnull=False).exists():
        return None
    required = Quiz.objects.filter(course=course, is_required=True, is_active=True)
    for quiz in required:
        if not quiz.attempts.filter(enrollment=enrollment, passed=True).exists():
            return None
    if course.final_exam_required:
        finals = Quiz.objects.filter(course=course, kind=Quiz.Kind.FINAL, is_required=True, is_active=True)
        if not finals.exists() or any(not q.attempts.filter(enrollment=enrollment, passed=True).exists() for q in finals):
            return None
    certificate = Certificate.objects.create(enrollment=enrollment)
    enrollment.certified_at = certificate.issued_at or timezone.now()
    enrollment.status = enrollment.Status.COMPLETED
    enrollment.save(update_fields=['certified_at', 'status', 'updated_at'])

    if getattr(settings, 'SMTP_CONFIGURED', False):
        verify_url = f"{settings.PUBLIC_BASE_URL}/certificados/verificar/{certificate.code}/"
        pdf_url = f"{settings.PUBLIC_BASE_URL}/certificados/{certificate.code}/pdf/"
        send_mail(
            subject=f'Certificado disponible · {course.title}',
            message=(
                f'Hola {enrollment.user.display_name},\n\n'
                f'Completaste satisfactoriamente “{course.title}”. Tu certificado ya está disponible.\n\n'
                f'Código: {certificate.code}\n'
                f'Descargar certificado: {pdf_url}\n'
                f'Validación pública: {verify_url}\n\n'
                'Felicitaciones por completar tu ruta de aprendizaje.\nDevlayer Academy'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[enrollment.user.email],
            fail_silently=True,
        )
    return certificate
