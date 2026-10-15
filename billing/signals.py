from django.conf import settings
from django.core.mail import send_mail
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from learning.models import Enrollment
from learning.services import create_or_activate_enrollment
from .models import Order, Payment


@receiver(pre_save, sender=Payment)
def remember_previous_payment_status(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_status = None
        return
    instance._previous_status = Payment.objects.filter(pk=instance.pk).values_list('status', flat=True).first()


@receiver(post_save, sender=Payment)
def activate_on_approval(sender, instance, created=False, **kwargs):
    previous = getattr(instance, '_previous_status', None)
    changed = created or previous != instance.status

    if instance.status == Payment.Status.APPROVED:
        if instance.order.status != Order.Status.PAID:
            Order.objects.filter(pk=instance.order_id).update(status=Order.Status.PAID)
        create_or_activate_enrollment(instance.order.user, instance.order.course, Enrollment.Source.PAYMENT)

        if changed and getattr(settings, 'SMTP_CONFIGURED', False):
            course_url = f"{settings.PUBLIC_BASE_URL}/academia/curso/{instance.order.course.slug}/"
            send_mail(
                subject=f'Pago aprobado · {instance.order.course.title}',
                message=(
                    f'Hola {instance.order.user.display_name},\n\n'
                    f'Tu pago de la orden {instance.order.code} fue aprobado. '
                    f'El acceso al curso “{instance.order.course.title}” ya está habilitado.\n\n'
                    f'Ingresar al curso: {course_url}\n\nDevlayer Academy'
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[instance.order.user.email],
                fail_silently=True,
            )

    elif instance.status == Payment.Status.REJECTED and changed and getattr(settings, 'SMTP_CONFIGURED', False):
        send_mail(
            subject=f'Comprobante requiere revisión · {instance.order.code}',
            message=(
                f'Hola {instance.order.user.display_name},\n\n'
                f'El comprobante de la orden {instance.order.code} fue marcado como rechazado. '
                'Ingresa a Devlayer Academy o comunícate con soporte para revisar el pago.\n\n'
                'Devlayer Academy'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[instance.order.user.email],
            fail_silently=True,
        )
