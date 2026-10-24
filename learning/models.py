import math
import uuid
from datetime import timedelta
from django.conf import settings
from django.db import models
from django.utils import timezone
from catalog.models import Course, Lesson

class Enrollment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Activo'
        BLOCKED = 'BLOCKED', 'Bloqueado'
        EXPIRED = 'EXPIRED', 'Vencido'
        COMPLETED = 'COMPLETED', 'Completado'
        REVOKED = 'REVOKED', 'Revocado'

    class Source(models.TextChoices):
        PAYMENT = 'PAYMENT', 'Pago'
        MANUAL = 'MANUAL', 'Manual'
        FREE = 'FREE', 'Gratuito'
        ADMIN = 'ADMIN', 'Administración'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    access_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='enrollments')
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name='enrollments')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    starts_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)
    blocked_reason = models.CharField(max_length=255, blank=True)
    certified_at = models.DateTimeField(null=True, blank=True)
    override_post_certificate_policy = models.CharField(max_length=20, choices=Course.PostCertificatePolicy.choices, blank=True)
    override_post_certificate_days = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'course'], name='unique_user_course_enrollment')]
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user} · {self.course}'

    def configure_default_expiry(self):
        if self.course.access_type == Course.AccessType.DAYS and self.course.access_days:
            self.expires_at = self.starts_at + timedelta(days=self.course.access_days)
        elif self.course.access_type == Course.AccessType.FIXED_DATE:
            self.expires_at = self.course.access_fixed_until
        else:
            self.expires_at = None

    @property
    def post_certificate_policy(self):
        return self.override_post_certificate_policy or self.course.post_certificate_policy

    @property
    def post_certificate_days(self):
        return self.override_post_certificate_days if self.override_post_certificate_days is not None else self.course.post_certificate_days

    @property
    def effective_access_end(self):
        """Fecha real de fin de acceso, si la modalidad tiene vencimiento."""
        if self.course.access_type == Course.AccessType.DAYS:
            if self.expires_at:
                return self.expires_at
            if self.course.access_days:
                return self.starts_at + timedelta(days=self.course.access_days)
            return None
        if self.course.access_type == Course.AccessType.FIXED_DATE:
            return self.expires_at or self.course.access_fixed_until
        if (
            self.course.access_type == Course.AccessType.UNTIL_CERTIFICATE
            and self.certified_at
            and self.post_certificate_policy == Course.PostCertificatePolicy.DAYS
            and self.post_certificate_days is not None
        ):
            return self.certified_at + timedelta(days=self.post_certificate_days)
        return None

    @property
    def access_days_remaining(self):
        end = self.effective_access_end
        if not end:
            return None
        seconds = (end - timezone.now()).total_seconds()
        return max(0, math.ceil(seconds / 86400))

    @property
    def student_access_label(self):
        if self.status == self.Status.BLOCKED:
            return 'Acceso bloqueado'
        if self.status == self.Status.REVOKED:
            return 'Acceso revocado'
        end = self.effective_access_end
        if end and timezone.now() > end:
            return 'Acceso vencido'
        access_type = self.course.access_type
        if access_type == Course.AccessType.PERMANENT:
            return 'Acceso permanente'
        if access_type == Course.AccessType.DAYS:
            days = self.access_days_remaining
            if days is None:
                configured = self.course.access_days or 0
                return f'{configured} días de acceso' if configured else 'Acceso por días'
            if days == 0:
                return 'Tu acceso finaliza hoy'
            if days == 1:
                return 'Te queda 1 día'
            return f'Te quedan {days} días'
        if access_type == Course.AccessType.FIXED_DATE:
            return 'Acceso con fecha límite'
        if access_type == Course.AccessType.UNTIL_CERTIFICATE:
            if not self.certified_at:
                return 'Acceso hasta certificarte'
            if self.post_certificate_policy == Course.PostCertificatePolicy.KEEP:
                return 'Acceso permanente después de certificarte'
            if self.post_certificate_policy == Course.PostCertificatePolicy.BLOCK:
                return 'Acceso finalizado al certificarte'
            days = self.access_days_remaining
            if days == 0:
                return 'Tu acceso adicional finaliza hoy'
            if days == 1:
                return 'Te queda 1 día adicional'
            if days is not None:
                return f'Te quedan {days} días adicionales'
            return 'Acceso posterior al certificado'
        return 'Acceso al curso'

    @property
    def student_access_detail(self):
        access_type = self.course.access_type
        if access_type == Course.AccessType.PERMANENT:
            return 'Este curso no tiene fecha de vencimiento.'
        if access_type == Course.AccessType.DAYS:
            return 'El plazo se cuenta desde la activación de tu matrícula.'
        if access_type == Course.AccessType.FIXED_DATE:
            return 'Tu acceso estará disponible hasta la fecha indicada.'
        if access_type == Course.AccessType.UNTIL_CERTIFICATE:
            if not self.certified_at:
                return 'Mantendrás acceso mientras completas los requisitos para obtener tu certificado.'
            if self.post_certificate_policy == Course.PostCertificatePolicy.KEEP:
                return 'Tu acceso continúa disponible aunque ya hayas obtenido el certificado.'
            if self.post_certificate_policy == Course.PostCertificatePolicy.BLOCK:
                return 'El acceso concluyó al emitirse tu certificado.'
            return 'Tu academia mantiene el acceso durante un período adicional después del certificado.'
        return ''

    def access_allowed(self):
        now = timezone.now()
        if self.status in {self.Status.BLOCKED, self.Status.REVOKED}:
            return False
        access_end = self.effective_access_end
        if access_end and now > access_end:
            return False
        # Las reglas posteriores al certificado solo pertenecen a la modalidad
        # "Hasta certificarse". Un curso permanente no puede bloquearse por certificar.
        if self.course.access_type == Course.AccessType.UNTIL_CERTIFICATE and self.certified_at:
            if self.post_certificate_policy == Course.PostCertificatePolicy.BLOCK:
                return False
            if self.post_certificate_policy == Course.PostCertificatePolicy.DAYS and self.post_certificate_days is not None:
                return now <= self.certified_at + timedelta(days=self.post_certificate_days)
        return self.status in {self.Status.ACTIVE, self.Status.COMPLETED}

class LessonProgress(models.Model):
    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name='lesson_progress')
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='progress_records')
    started_at = models.DateTimeField(auto_now_add=True)
    last_viewed_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    views_count = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['enrollment', 'lesson'], name='unique_lesson_progress')]

    @property
    def completed(self):
        return bool(self.completed_at)

    def __str__(self):
        return f'{self.enrollment} · {self.lesson}'
