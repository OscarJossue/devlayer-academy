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

    def access_allowed(self):
        now = timezone.now()
        if self.status in {self.Status.BLOCKED, self.Status.REVOKED}:
            return False
        if self.expires_at and now > self.expires_at:
            return False
        if self.certified_at:
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
