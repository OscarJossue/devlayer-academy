import uuid
from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from catalog.models import Course

class BankAccount(models.Model):
    bank_name = models.CharField(max_length=120)
    account_type = models.CharField(max_length=80, blank=True)
    account_number = models.CharField(max_length=80)
    holder_name = models.CharField(max_length=180)
    holder_id = models.CharField(max_length=40, blank=True)
    instructions = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'bank_name']

    def __str__(self):
        return f'{self.bank_name} · {self.account_number}'

class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pendiente'
        PAID = 'PAID', 'Pagada'
        REJECTED = 'REJECTED', 'Rechazada'
        CANCELLED = 'CANCELLED', 'Cancelada'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=30, unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='orders')
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name='orders')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.code:
            from django.utils import timezone
            stamp = timezone.now().strftime('%y%m%d')
            suffix = uuid.uuid4().hex[:6].upper()
            self.code = f'DVA-{stamp}-{suffix}'
        super().save(*args, **kwargs)

    def __str__(self):
        return self.code

class Payment(models.Model):
    class Method(models.TextChoices):
        BANK = 'BANK', 'Transferencia bancaria'
        WHATSAPP = 'WHATSAPP', 'Reportado por WhatsApp'
        MANUAL = 'MANUAL', 'Registro manual'
        PAYPHONE = 'PAYPHONE', 'PayPhone'
        PAYPAL = 'PAYPAL', 'PayPal'
        CARD = 'CARD', 'Tarjeta mediante link'
        PAYMENT_LINK = 'PAYMENT_LINK', 'Link de pago'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pendiente'
        APPROVED = 'APPROVED', 'Aprobado'
        REJECTED = 'REJECTED', 'Rechazado'
        REFUNDED = 'REFUNDED', 'Reembolsado'
        CANCELLED = 'CANCELLED', 'Cancelado'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name='payments')
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.BANK)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.CharField(max_length=120, blank=True)
    proof = models.FileField(upload_to='private/payment_proofs/%Y/%m/', blank=True, null=True, validators=[FileExtensionValidator(['pdf', 'jpg', 'jpeg', 'png', 'webp'])])
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='payments_approved')
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.order.code} · {self.get_status_display()}'
