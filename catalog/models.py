import uuid
from urllib.parse import urlparse, parse_qs
from django.conf import settings
from django.core.validators import FileExtensionValidator, MinValueValidator, MaxValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from core.fields import EncryptedTextField

class Category(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField(blank=True)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='children')
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']
        verbose_name_plural = 'Categorías'

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class Course(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Borrador'
        REVIEW = 'REVIEW', 'En revisión'
        CHANGES = 'CHANGES', 'Cambios solicitados'
        APPROVED = 'APPROVED', 'Aprobado'
        PUBLISHED = 'PUBLISHED', 'Publicado'
        PAUSED = 'PAUSED', 'Pausado'
        ARCHIVED = 'ARCHIVED', 'Archivado'

    class AccessType(models.TextChoices):
        PERMANENT = 'PERMANENT', 'Permanente'
        DAYS = 'DAYS', 'Cantidad de días'
        FIXED_DATE = 'FIXED_DATE', 'Hasta fecha fija'
        UNTIL_CERTIFICATE = 'UNTIL_CERTIFICATE', 'Hasta certificarse'

    class PostCertificatePolicy(models.TextChoices):
        KEEP = 'KEEP', 'Mantener acceso'
        BLOCK = 'BLOCK', 'Bloquear al certificar'
        DAYS = 'DAYS', 'Mantener X días después'

    class CertificateStyleMode(models.TextChoices):
        ACADEMY = 'ACADEMY', 'Usar diseño de la academia'
        CUSTOM = 'CUSTOM', 'Diseño personalizado para este curso'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, unique=True)
    short_description = models.CharField(max_length=280, blank=True)
    description = models.TextField(blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='courses')
    thumbnail = models.ImageField(upload_to='course_thumbnails/%Y/%m/', blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default='USD')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    sequential_learning = models.BooleanField(default=True)
    default_pass_percentage = models.PositiveSmallIntegerField(default=70, validators=[MinValueValidator(1), MaxValueValidator(100)])
    access_type = models.CharField(max_length=30, choices=AccessType.choices, default=AccessType.PERMANENT)
    access_days = models.PositiveIntegerField(null=True, blank=True)
    access_fixed_until = models.DateTimeField(null=True, blank=True)
    post_certificate_policy = models.CharField(max_length=20, choices=PostCertificatePolicy.choices, default=PostCertificatePolicy.BLOCK)
    post_certificate_days = models.PositiveIntegerField(null=True, blank=True)
    final_exam_required = models.BooleanField(default=True)

    # Certificación es una decisión por curso. El diseño puede heredarse de la academia
    # o personalizarse sin modificar el estilo global.
    certificate_enabled = models.BooleanField(default=True, verbose_name='Este curso otorga certificado')
    certificate_style_mode = models.CharField(max_length=20, choices=CertificateStyleMode.choices, default=CertificateStyleMode.ACADEMY, verbose_name='Diseño del certificado')
    certificate_custom_title = models.CharField(max_length=180, blank=True, verbose_name='Título personalizado')
    certificate_custom_subtitle = models.CharField(max_length=180, blank=True, verbose_name='Texto previo al estudiante')
    certificate_custom_body = models.CharField(max_length=240, blank=True, verbose_name='Texto previo al curso')
    certificate_custom_accent_color = models.CharField(max_length=7, blank=True, verbose_name='Color de acento')
    certificate_custom_background_color = models.CharField(max_length=7, blank=True, verbose_name='Color de fondo')
    certificate_custom_text_color = models.CharField(max_length=7, blank=True, verbose_name='Color de texto')
    certificate_custom_signature_name = models.CharField(max_length=160, blank=True, verbose_name='Nombre de la firma')
    certificate_custom_signature_role = models.CharField(max_length=160, blank=True, verbose_name='Cargo de la firma')
    certificate_custom_signature_image = models.ImageField(upload_to='course_certificates/signatures/%Y/%m/', blank=True, null=True, verbose_name='Imagen de firma')
    certificate_custom_footer = models.CharField(max_length=240, blank=True, verbose_name='Texto inferior')
    certificate_custom_show_qr = models.BooleanField(default=True, verbose_name='Mostrar código QR')
    certificate_custom_show_logo = models.BooleanField(default=True, verbose_name='Mostrar logo de la academia')

    # Clase magistral / sesión en vivo opcional al final del curso.
    masterclass_enabled = models.BooleanField(default=False, verbose_name='Habilitar clase magistral')
    masterclass_title = models.CharField(max_length=180, blank=True, default='Clase magistral y resolución de dudas', verbose_name='Título')
    masterclass_description = models.TextField(blank=True, verbose_name='Descripción')
    masterclass_meeting_url = models.URLField(max_length=500, blank=True, verbose_name='Enlace de videoconferencia')
    masterclass_scheduled_at = models.DateTimeField(null=True, blank=True, verbose_name='Fecha y hora')
    masterclass_duration_minutes = models.PositiveIntegerField(default=60, verbose_name='Duración aproximada (minutos)')

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='courses_created')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='courses_approved')
    approved_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title) or 'curso'
            slug = base
            i = 2
            while Course.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                slug = f'{base}-{i}'
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('catalog:course_detail', args=[self.slug])

    @property
    def estimated_duration_minutes(self):
        """Duración aproximada calculada desde las clases publicadas."""
        total = 0
        for module in self.modules.filter(is_published=True).prefetch_related('lessons'):
            total += sum(
                int(lesson.duration_minutes or 0)
                for lesson in module.lessons.all()
                if lesson.is_published
            )
        return total

    @property
    def estimated_duration_label(self):
        minutes = self.estimated_duration_minutes
        if minutes <= 0:
            return 'Duración por definir'
        hours, remaining = divmod(minutes, 60)
        if hours and remaining:
            return f'{hours} h {remaining} min'
        if hours:
            return f'{hours} h'
        return f'{remaining} min'

    @property
    def lead_instructor(self):
        """Profesor principal para tarjetas y portada del curso."""
        links = list(self.instructor_links.all())
        link = next((item for item in links if item.is_owner), None) or (links[0] if links else None)
        return link.user if link else None

    def __str__(self):
        return self.title

class CourseInstructor(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='instructor_links')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='course_links')
    is_owner = models.BooleanField(default=False)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['course', 'user'], name='unique_course_instructor')]

    def __str__(self):
        return f'{self.user} · {self.course}'

class Module(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='modules')
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=1)
    is_published = models.BooleanField(default=True)
    requires_quiz_to_unlock_next = models.BooleanField(default=True)

    class Meta:
        ordering = ['order', 'id']
        constraints = [models.UniqueConstraint(fields=['course', 'order'], name='unique_module_order_per_course')]

    def __str__(self):
        return f'{self.course} · {self.order}. {self.title}'

class Lesson(models.Model):
    class VideoProvider(models.TextChoices):
        YOUTUBE = 'YOUTUBE', 'YouTube'
        EXTERNAL = 'EXTERNAL', 'Otro / futuro streaming'
        NONE = 'NONE', 'Sin video'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name='lessons')
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=1)
    duration_minutes = models.PositiveIntegerField(default=0)
    video_provider = models.CharField(max_length=20, choices=VideoProvider.choices, default=VideoProvider.YOUTUBE)
    video_source = EncryptedTextField(blank=True, help_text='URL/ID cifrado en la base de datos.')
    material_pdf = models.FileField(upload_to='private/materials/%Y/%m/', blank=True, null=True, validators=[FileExtensionValidator(['pdf'])])
    is_preview = models.BooleanField(default=False)
    is_published = models.BooleanField(default=True)

    class Meta:
        ordering = ['order', 'id']
        constraints = [models.UniqueConstraint(fields=['module', 'order'], name='unique_lesson_order_per_module')]

    def youtube_id(self):
        value = (self.video_source or '').strip()
        if not value:
            return ''
        if '/' not in value and '?' not in value and len(value) <= 32:
            return value
        try:
            parsed = urlparse(value)
            if parsed.hostname in {'youtu.be'}:
                return parsed.path.strip('/').split('/')[0]
            if parsed.hostname and 'youtube.com' in parsed.hostname:
                if parsed.path.startswith('/embed/'):
                    return parsed.path.split('/embed/', 1)[1].split('/')[0]
                return parse_qs(parsed.query).get('v', [''])[0]
        except Exception:
            return ''
        return ''

    def embed_url(self):
        vid = self.youtube_id()
        return (
            f'https://www.youtube-nocookie.com/embed/{vid}'
            '?rel=0&modestbranding=1&controls=1&fs=1&playsinline=1&iv_load_policy=3'
        ) if vid else ''

    def __str__(self):
        return f'{self.module} · {self.order}. {self.title}'
