from django.conf import settings
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from learning.models import Enrollment
from learning.services import create_or_activate_enrollment
from tenancy.mail import academy_mail_available, send_academy_mail
from tenancy.services import academy_for_course
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
    academy = academy_for_course(instance.order.course)
    academy_name = academy.name if academy else 'Academia'

    if instance.status == Payment.Status.APPROVED:
        if instance.order.status != Order.Status.PAID:
            Order.objects.filter(pk=instance.order_id).update(status=Order.Status.PAID)
        try:
            create_or_activate_enrollment(instance.order.user, instance.order.course, Enrollment.Source.PAYMENT)
        except PermissionError:
            return
        if changed and academy and academy_mail_available(academy):
            base = settings.PUBLIC_BASE_URL.rstrip('/')
            course_url = f'{base}/academy/{academy.slug}/curso/{instance.order.course.slug}/'
            send_academy_mail(
                academy,
                subject=f'Pago aprobado · {instance.order.course.title}',
                message=(
                    f'Hola {instance.order.user.display_name},\n\nTu pago de la orden {instance.order.code} fue aprobado. '
                    f'El acceso al curso “{instance.order.course.title}” ya está habilitado.\n\n'
                    f'Ingresar al curso: {course_url}\n\n{academy_name}'
                ),
                recipients=[instance.order.user.email],
                fail_silently=True,
                html_message=(
                    f'<div style="font-family:Arial,sans-serif;color:#172033"><img src="cid:academy-logo" alt="{academy_name}" style="display:block;max-width:180px;max-height:64px;object-fit:contain;margin-bottom:20px">'
                    f'<h2>Pago aprobado</h2><p>Hola <strong>{instance.order.user.display_name}</strong>.</p>'
                    f'<p>Tu pago de la orden <strong>{instance.order.code}</strong> fue aprobado y el curso <strong>{instance.order.course.title}</strong> ya está habilitado.</p>'
                    f'<p><a href="{course_url}">Ingresar al curso</a></p></div>'
                ),
                attach_brand_logo=True,
            )
    elif instance.status == Payment.Status.REJECTED and changed and academy and academy_mail_available(academy):
        send_academy_mail(
            academy,
            subject=f'Comprobante requiere revisión · {instance.order.code}',
            message=(
                f'Hola {instance.order.user.display_name},\n\nEl comprobante de la orden {instance.order.code} fue marcado como rechazado. '
                f'Ingresa a {academy_name} o comunícate con soporte para revisar el pago.'
            ),
            recipients=[instance.order.user.email],
            fail_silently=True,
            html_message=(
                f'<div style="font-family:Arial,sans-serif;color:#172033"><img src="cid:academy-logo" alt="{academy_name}" style="display:block;max-width:180px;max-height:64px;object-fit:contain;margin-bottom:20px">'
                f'<h2>Comprobante requiere revisión</h2><p>Hola <strong>{instance.order.user.display_name}</strong>.</p>'
                f'<p>El comprobante de la orden <strong>{instance.order.code}</strong> fue marcado como rechazado. Contacta a la academia para revisarlo.</p></div>'
            ),
            attach_brand_logo=True,
        )
