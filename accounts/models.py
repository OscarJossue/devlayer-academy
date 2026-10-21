import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models
from .managers import UserManager

class User(AbstractUser):
    class Role(models.TextChoices):
        STUDENT = 'STUDENT', 'Estudiante'
        PROFESSOR = 'PROFESSOR', 'Profesor'
        ADMIN = 'ADMIN', 'Administrador'
        OWNER = 'OWNER', 'Dueño de academia'
        SUPERADMIN = 'SUPERADMIN', 'Superadministrador del sistema'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = None
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    email_verified = models.BooleanField(default=False)
    phone = models.CharField(max_length=30, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []
    objects = UserManager()

    class Meta:
        ordering = ['-date_joined']

    def save(self, *args, **kwargs):
        self.email = self.email.lower().strip()
        if self.is_superuser:
            self.role = self.Role.SUPERADMIN
            self.is_staff = True
            self.email_verified = True
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        full = self.get_full_name().strip()
        return full or self.email

    def __str__(self):
        return self.display_name
