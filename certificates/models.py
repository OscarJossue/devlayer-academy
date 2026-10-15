import uuid
from django.conf import settings
from django.db import models
from learning.models import Enrollment

class Certificate(models.Model):
    class Status(models.TextChoices):
        VALID = 'VALID', 'Válido'
        REVOKED = 'REVOKED', 'Revocado'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    enrollment = models.OneToOneField(Enrollment, on_delete=models.PROTECT, related_name='certificate')
    code = models.CharField(max_length=40, unique=True, editable=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.VALID)
    issued_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=255, blank=True)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='certificates_issued')

    class Meta:
        ordering = ['-issued_at']

    def save(self, *args, **kwargs):
        if not self.code:
            from django.utils import timezone
            prefix = timezone.now().strftime('DEV-%Y')
            self.code = f'{prefix}-{uuid.uuid4().hex[:10].upper()}'
        super().save(*args, **kwargs)

    def __str__(self):
        return self.code
