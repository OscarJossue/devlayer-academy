import uuid
from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from core.fields import EncryptedTextField


class Academy(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=190, unique=True)
    legal_name = models.CharField(max_length=220, blank=True)
    tax_id = models.CharField(max_length=60, blank=True)
    contact_email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    custom_domain = models.CharField(max_length=255, blank=True, unique=True, null=True)
    logo = models.ImageField(upload_to='academy_branding/%Y/%m/', blank=True, null=True)
    brand_color = models.CharField(max_length=7, default='#1458D6', verbose_name='Color principal')
    tagline = models.CharField(max_length=160, blank=True, verbose_name='Frase principal')
    public_description = models.TextField(blank=True, verbose_name='Descripción pública')

    # Soporte visible dentro de la academia. Estos contactos pertenecen al cliente
    # y nunca deben mezclarse con el WhatsApp interno de DevLayer Studio.
    support_title = models.CharField(
        max_length=90, blank=True, default='Soporte de la academia',
        verbose_name='Nombre del panel de soporte',
    )
    support_whatsapp_1_label = models.CharField(
        max_length=60, blank=True, verbose_name='Etiqueta del WhatsApp 1',
    )
    support_whatsapp_1_number = models.CharField(
        max_length=30, blank=True, verbose_name='WhatsApp 1',
    )
    support_whatsapp_2_label = models.CharField(
        max_length=60, blank=True, verbose_name='Etiqueta del WhatsApp 2',
    )
    support_whatsapp_2_number = models.CharField(
        max_length=30, blank=True, verbose_name='WhatsApp 2',
    )

    # Cobros configurables por academia. Ninguna academia comparte métodos de pago.
    payment_transfer_enabled = models.BooleanField(default=True, verbose_name='Aceptar transferencia bancaria')
    payment_paypal_enabled = models.BooleanField(default=False, verbose_name='Aceptar PayPal')
    payment_paypal_email = models.EmailField(blank=True, verbose_name='Correo de PayPal')
    payment_paypal_url = models.URLField(blank=True, verbose_name='Enlace de PayPal')
    payment_payphone_enabled = models.BooleanField(default=False, verbose_name='Aceptar PayPhone')
    payment_payphone_reference = models.CharField(max_length=120, blank=True, verbose_name='Dato de PayPhone')
    payment_payphone_url = models.URLField(blank=True, verbose_name='Enlace de PayPhone')
    payment_card_enabled = models.BooleanField(default=False, verbose_name='Aceptar tarjeta mediante link solicitado por WhatsApp')
    payment_card_instructions = models.CharField(
        max_length=220, blank=True,
        default='Solicita tu link de pago por WhatsApp y completa el pago con tarjeta.',
        verbose_name='Indicaciones para tarjeta',
    )
    payment_link_1_enabled = models.BooleanField(default=False, verbose_name='Habilitar link de pago 1')
    payment_link_1_label = models.CharField(max_length=80, blank=True, verbose_name='Nombre del link de pago 1')
    payment_link_1_url = models.URLField(blank=True, verbose_name='URL del link de pago 1')
    payment_link_2_enabled = models.BooleanField(default=False, verbose_name='Habilitar link de pago 2')
    payment_link_2_label = models.CharField(max_length=80, blank=True, verbose_name='Nombre del link de pago 2')
    payment_link_2_url = models.URLField(blank=True, verbose_name='URL del link de pago 2')
    payment_whatsapp_enabled = models.BooleanField(default=False, verbose_name='Aceptar soporte/reporte de pago por WhatsApp')
    payment_whatsapp_number = models.CharField(max_length=30, blank=True, verbose_name='WhatsApp para pagos')
    payment_instructions = models.TextField(blank=True, verbose_name='Indicaciones generales de pago')

    # SMTP propio de cada academia. La contraseña se cifra antes de persistirse.
    smtp_enabled = models.BooleanField(default=False, verbose_name='SMTP habilitado')
    smtp_host = models.CharField(max_length=255, blank=True, verbose_name='Servidor SMTP')
    smtp_port = models.PositiveIntegerField(default=587, verbose_name='Puerto SMTP')
    smtp_username = models.CharField(max_length=255, blank=True, verbose_name='Usuario SMTP')
    smtp_password = EncryptedTextField(blank=True, verbose_name='Contraseña SMTP')
    smtp_use_tls = models.BooleanField(default=True, verbose_name='Usar STARTTLS')
    smtp_use_ssl = models.BooleanField(default=False, verbose_name='Usar SSL')
    smtp_from_email = models.EmailField(blank=True, verbose_name='Correo remitente')
    smtp_from_name = models.CharField(max_length=160, blank=True, verbose_name='Nombre remitente')

    # Diseño predeterminado de certificados de la academia. Los cursos pueden heredarlo
    # o definir una variación propia sin afectar a los demás cursos.
    certificate_title = models.CharField(max_length=180, default='Certificado de finalización', verbose_name='Título del certificado')
    certificate_subtitle = models.CharField(max_length=180, default='Se certifica que', verbose_name='Texto previo al estudiante')
    certificate_body = models.CharField(max_length=240, default='ha completado satisfactoriamente el curso', verbose_name='Texto previo al curso')
    certificate_accent_color = models.CharField(max_length=7, blank=True, default='', verbose_name='Color de acento del certificado')
    certificate_background_color = models.CharField(max_length=7, default='#FFFFFF', verbose_name='Fondo del certificado')
    certificate_text_color = models.CharField(max_length=7, default='#172033', verbose_name='Color del texto del certificado')
    certificate_signature_name = models.CharField(max_length=160, blank=True, verbose_name='Nombre de la firma')
    certificate_signature_role = models.CharField(max_length=160, blank=True, verbose_name='Cargo de la firma')
    certificate_signature_image = models.ImageField(upload_to='academy_certificates/signatures/%Y/%m/', blank=True, null=True, verbose_name='Imagen de firma')
    certificate_footer = models.CharField(max_length=240, blank=True, default='Certificado verificable digitalmente.', verbose_name='Texto inferior')
    certificate_show_qr = models.BooleanField(default=True, verbose_name='Mostrar código QR')
    certificate_show_logo = models.BooleanField(default=True, verbose_name='Mostrar logo de la academia')

    # Política local de acceso: permite al dueño resolver incidencias de SMTP sin
    # marcar el correo global del usuario como verificado.
    allow_unverified_approvals = models.BooleanField(default=False, verbose_name='Permitir aprobaciones sin verificar correo')

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Academia'
        verbose_name_plural = 'Academias'

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or 'academia'
            candidate = base
            index = 2
            while Academy.objects.exclude(pk=self.pk).filter(slug=candidate).exists():
                candidate = f'{base}-{index}'
                index += 1
            self.slug = candidate
        if self.custom_domain:
            self.custom_domain = self.custom_domain.strip().lower().split(':')[0]
        else:
            self.custom_domain = None
        if self.smtp_use_ssl:
            self.smtp_use_tls = False
        super().save(*args, **kwargs)

    @property
    def current_license(self):
        try:
            return self.license
        except AcademyLicense.DoesNotExist:
            return None

    @property
    def access_enabled(self):
        license_obj = self.current_license
        return bool(self.is_active and license_obj and license_obj.is_valid)

    @property
    def smtp_configured(self):
        return bool(
            self.smtp_enabled
            and self.smtp_host
            and self.smtp_port
            and self.smtp_username
            and self.smtp_password
            and self.smtp_from_email
        )

    @property
    def smtp_sender(self):
        if not self.smtp_from_email:
            return ''
        name = (self.smtp_from_name or self.name).strip()
        return f'{name} <{self.smtp_from_email}>' if name else self.smtp_from_email

    def __str__(self):
        return self.name


class PlatformEmailSettings(models.Model):
    """SMTP transaccional global de DevLayer Studio.

    Las academias que no configuran un dominio propio heredan este proveedor.
    La contraseña se almacena con ``EncryptedTextField`` y nunca se expone en
    plantillas ni respuestas. Solo existe una fila (pk=1).
    """
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    is_enabled = models.BooleanField(default=False, verbose_name='Correo global habilitado')
    smtp_host = models.CharField(max_length=255, blank=True, verbose_name='Servidor SMTP')
    smtp_port = models.PositiveIntegerField(default=587, verbose_name='Puerto SMTP')
    smtp_username = models.CharField(max_length=255, blank=True, verbose_name='Usuario SMTP')
    smtp_password = EncryptedTextField(blank=True, verbose_name='Contraseña SMTP')
    smtp_use_tls = models.BooleanField(default=True, verbose_name='Usar STARTTLS')
    smtp_use_ssl = models.BooleanField(default=False, verbose_name='Usar SSL')
    smtp_from_email = models.EmailField(blank=True, verbose_name='Correo remitente')
    smtp_from_name = models.CharField(max_length=160, blank=True, default='DevLayer Studio', verbose_name='Nombre remitente')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Correo global de la plataforma'
        verbose_name_plural = 'Correo global de la plataforma'

    def save(self, *args, **kwargs):
        self.pk = 1
        if self.smtp_use_ssl:
            self.smtp_use_tls = False
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def configured(self):
        return bool(
            self.is_enabled
            and self.smtp_host
            and self.smtp_port
            and self.smtp_username
            and self.smtp_password
            and self.smtp_from_email
        )

    @property
    def sender(self):
        if not self.smtp_from_email:
            return ''
        name = (self.smtp_from_name or 'DevLayer Studio').strip()
        return f'{name} <{self.smtp_from_email}>' if name else self.smtp_from_email

    def __str__(self):
        return 'SMTP global · DevLayer Studio'


class AcademyPlan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, unique=True, verbose_name='Nombre del plan')
    code = models.SlugField(max_length=140, unique=True, blank=True, verbose_name='Código')
    description = models.TextField(blank=True, verbose_name='Descripción')
    max_students = models.PositiveIntegerField(default=100, verbose_name='Máximo de estudiantes activos', help_text='0 = ilimitados')
    max_professors = models.PositiveIntegerField(default=5, verbose_name='Máximo de profesores', help_text='0 = ilimitados')
    max_admins = models.PositiveIntegerField(default=2, verbose_name='Máximo de administradores', help_text='0 = ilimitados')
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Precio')
    currency = models.CharField(max_length=8, default='USD', verbose_name='Moneda')
    duration_days = models.PositiveIntegerField(default=365, verbose_name='Duración en días', help_text='0 = sin vencimiento automático')
    is_active = models.BooleanField(default=True, verbose_name='Disponible para nuevas licencias')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['price', 'name']
        verbose_name = 'Plan de academia'
        verbose_name_plural = 'Planes de academias'

    def save(self, *args, **kwargs):
        if not self.code:
            base = slugify(self.name) or 'plan'
            candidate = base
            index = 2
            while AcademyPlan.objects.exclude(pk=self.pk).filter(code=candidate).exists():
                candidate = f'{base}-{index}'
                index += 1
            self.code = candidate
        self.currency = (self.currency or 'USD').upper().strip()
        super().save(*args, **kwargs)

    @property
    def limits_summary(self):
        def fmt(value):
            return 'Ilimitados' if not value else str(value)
        return f'{fmt(self.max_students)} estudiantes · {fmt(self.max_professors)} profesores · {fmt(self.max_admins)} administradores'

    def __str__(self):
        return self.name


class AcademyLicense(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Activa'
        SUSPENDED = 'SUSPENDED', 'Suspendida'
        CANCELLED = 'CANCELLED', 'Cancelada'

    class FinancialStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pendiente de cobro'
        PARTIAL = 'PARTIAL', 'Pago parcial'
        PAID = 'PAID', 'Pagada'
        COURTESY = 'COURTESY', 'Cortesía'

    academy = models.OneToOneField(Academy, on_delete=models.CASCADE, related_name='license')
    plan = models.ForeignKey(AcademyPlan, null=True, blank=True, on_delete=models.SET_NULL, related_name='licenses', verbose_name='Plan comercial')
    plan_name = models.CharField(max_length=120, default='Academy')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    starts_at = models.DateField(default=timezone.localdate)
    ends_at = models.DateField(null=True, blank=True)
    # Compatibilidad: max_users pasa a representar estudiantes activos/pending de la academia.
    max_users = models.PositiveIntegerField(default=0, help_text='0 = estudiantes ilimitados')
    max_professors = models.PositiveIntegerField(default=0, help_text='0 = profesores ilimitados')
    max_admins = models.PositiveIntegerField(default=0, help_text='0 = administradores ilimitados')
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Valor de la licencia')
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Valor cobrado')
    currency = models.CharField(max_length=8, default='USD', verbose_name='Moneda')
    financial_status = models.CharField(
        max_length=20, choices=FinancialStatus.choices, default=FinancialStatus.PENDING,
        verbose_name='Estado financiero',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Licencia de academia'
        verbose_name_plural = 'Licencias de academias'

    @property
    def is_valid(self):
        today = timezone.localdate()
        if self.status != self.Status.ACTIVE:
            return False
        if self.starts_at and today < self.starts_at:
            return False
        if self.ends_at and today > self.ends_at:
            return False
        return True

    @property
    def effective_status(self):
        if self.status != self.Status.ACTIVE:
            return self.get_status_display()
        today = timezone.localdate()
        if self.starts_at and today < self.starts_at:
            return 'Pendiente de inicio'
        if self.ends_at and today > self.ends_at:
            return 'Vencida'
        return 'Activa'

    @property
    def days_remaining(self):
        if not self.ends_at:
            return None
        return (self.ends_at - timezone.localdate()).days

    @property
    def total_days(self):
        if not self.starts_at or not self.ends_at:
            return None
        return max((self.ends_at - self.starts_at).days + 1, 1)

    @property
    def daily_cost(self):
        days = self.total_days
        if not days or not self.price:
            return Decimal('0.00')
        return (self.price / Decimal(days)).quantize(Decimal('0.01'))

    @property
    def balance_due(self):
        value = (self.price or Decimal('0')) - (self.amount_paid or Decimal('0'))
        return max(value, Decimal('0')).quantize(Decimal('0.01'))

    @property
    def days_elapsed(self):
        if not self.starts_at:
            return 0
        today = timezone.localdate()
        if today < self.starts_at:
            return 0
        upper = min(today, self.ends_at) if self.ends_at else today
        return max((upper - self.starts_at).days + 1, 0)

    @property
    def consumed_value(self):
        if not self.total_days:
            return Decimal('0.00')
        days = min(self.days_elapsed, self.total_days)
        return (self.daily_cost * Decimal(days)).quantize(Decimal('0.01'))

    @property
    def expiry_progress(self):
        if not self.total_days:
            return 0
        return min(100, max(0, round((self.days_elapsed / self.total_days) * 100)))

    @property
    def is_expiring_soon(self):
        remaining = self.days_remaining
        return remaining is not None and 0 <= remaining <= 30

    @property
    def max_students(self):
        return self.max_users

    def role_limit(self, role):
        mapping = {
            'STUDENT': self.max_users,
            'PROFESSOR': self.max_professors,
            'ADMIN': self.max_admins,
            'OWNER': 1,
        }
        return mapping.get(str(role), 0)

    def role_usage(self, role):
        membership_model = globals().get('AcademyMembership')
        if membership_model is None:
            return 0
        return membership_model.objects.filter(
            academy=self.academy,
            role=role,
            status=membership_model.Status.ACTIVE,
        ).count()

    def role_available(self, role, exclude_membership=None):
        limit = self.role_limit(role)
        if not limit:
            return True
        membership_model = globals().get('AcademyMembership')
        if membership_model is None:
            return True
        qs = membership_model.objects.filter(
            academy=self.academy, role=role, status=membership_model.Status.ACTIVE
        )
        if exclude_membership is not None:
            qs = qs.exclude(pk=exclude_membership.pk)
        return qs.count() < limit

    def extend(self, days):
        today = timezone.localdate()
        base = self.ends_at if self.ends_at and self.ends_at >= today else today
        self.ends_at = base + timedelta(days=days)
        self.status = self.Status.ACTIVE
        self.save(update_fields=['ends_at', 'status', 'updated_at'])

    def __str__(self):
        return f'{self.academy.name} · {self.effective_status}'


class AcademyMembership(models.Model):
    class Role(models.TextChoices):
        STUDENT = 'STUDENT', 'Estudiante'
        PROFESSOR = 'PROFESSOR', 'Profesor'
        ADMIN = 'ADMIN', 'Administrador'
        OWNER = 'OWNER', 'Dueño de academia'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pendiente de aprobación'
        ACTIVE = 'ACTIVE', 'Activo'
        BLOCKED = 'BLOCKED', 'Bloqueado'
        REJECTED = 'REJECTED', 'Rechazado'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    academy = models.ForeignKey(Academy, on_delete=models.CASCADE, related_name='memberships')
    user_id = models.UUIDField(db_index=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by_id = models.UUIDField(null=True, blank=True)
    # Excepción por academia: permite aprobar una membresía aunque el correo global
    # todavía no haya sido verificado. No afecta a otras academias del mismo usuario.
    email_verification_bypassed = models.BooleanField(default=False, verbose_name='Autorizado sin verificación de correo')
    # Permiso delegado por el dueño. Solo habilita operaciones sobre estudiantes
    # y pagos de los cursos donde el profesor está asignado; nunca concede acceso
    # administrativo global a la academia.
    can_manage_student_payments = models.BooleanField(
        default=False,
        verbose_name='Puede gestionar estudiantes y pagos de sus cursos',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        constraints = [
            models.UniqueConstraint(fields=['academy', 'user_id'], name='unique_academy_user_membership'),
        ]

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE and self.academy.access_enabled

    def __str__(self):
        return f'{self.user_id} · {self.academy.name} · {self.get_role_display()}'


class AcademyCourse(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    academy = models.ForeignKey(Academy, on_delete=models.CASCADE, related_name='course_bindings')
    course_id = models.UUIDField(unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AcademyCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    academy = models.ForeignKey(Academy, on_delete=models.CASCADE, related_name='category_bindings')
    category_id = models.UUIDField(unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AcademyBankAccount(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    academy = models.ForeignKey(Academy, on_delete=models.CASCADE, related_name='bank_bindings')
    bank_account_id = models.BigIntegerField(unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)


class PlatformAuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor_email = models.EmailField(blank=True)
    academy = models.ForeignKey(Academy, null=True, blank=True, on_delete=models.SET_NULL, related_name='platform_events')
    action = models.CharField(max_length=120)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
