from django.db import transaction
from django.utils import timezone
from learning.models import Enrollment
from learning.services import create_or_activate_enrollment
from .models import Order, Payment

@transaction.atomic
def approve_payment(payment, actor=None):
    payment.status = Payment.Status.APPROVED
    payment.approved_by = actor
    payment.approved_at = timezone.now()
    payment.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
    payment.order.status = Order.Status.PAID
    payment.order.save(update_fields=['status', 'updated_at'])
    return create_or_activate_enrollment(payment.order.user, payment.order.course, Enrollment.Source.PAYMENT)
