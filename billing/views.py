from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

from core.decorators import superadmin_required, verified_email_required
from catalog.models import Course
from learning.models import Enrollment
from learning.services import create_or_activate_enrollment
from tenancy.services import scope_banks, scope_courses
from .forms import PaymentProofForm
from .models import BankAccount, Order, Payment


@verified_email_required
def history(request):
    course_ids = scope_courses(Course.objects.all(), request.academy).values_list('pk', flat=True)
    orders = Order.objects.filter(user=request.user, course_id__in=course_ids).select_related('course').prefetch_related('payments').order_by('-created_at')
    return render(request, 'billing/history.html', {'orders': orders})


@verified_email_required
def checkout(request, course_slug):
    course = get_object_or_404(
        scope_courses(Course.objects.filter(status__in=[Course.Status.APPROVED, Course.Status.PUBLISHED]), request.academy),
        slug=course_slug,
    )
    existing = Enrollment.objects.filter(user=request.user, course=course).first()
    if existing and existing.access_allowed():
        messages.info(request, 'Ya tienes acceso a este curso.')
        return redirect('learning:course_player', course_slug=course.slug)
    if course.price == 0:
        create_or_activate_enrollment(request.user, course, Enrollment.Source.FREE)
        messages.success(request, 'Curso habilitado.')
        return redirect('learning:course_player', course_slug=course.slug)
    order = Order.objects.filter(user=request.user, course=course, status=Order.Status.PENDING).order_by('-created_at').first()
    if not order:
        order = Order.objects.create(user=request.user, course=course, amount=course.price, currency=course.currency)
    return redirect('billing:order', order.id)


@verified_email_required
def order_detail(request, order_id):
    course_ids = scope_courses(Course.objects.all(), request.academy).values_list('pk', flat=True)
    order = get_object_or_404(Order, id=order_id, user=request.user, course_id__in=course_ids)
    payment = order.payments.filter(status=Payment.Status.PENDING).order_by('-created_at').first()
    form = PaymentProofForm(request.POST or None, request.FILES or None, instance=payment, academy=request.academy)
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        obj.order = order
        obj.amount = order.amount
        obj.status = Payment.Status.PENDING
        obj.save()
        messages.success(request, 'Comprobante registrado. Se habilitará el curso al aprobar el pago.')
        return redirect('billing:order', order.id)
    academy = request.academy
    whatsapp_url = ''
    if academy.payment_whatsapp_enabled and academy.payment_whatsapp_number:
        msg = quote(f'Hola, deseo reportar el pago del curso {order.course.title}. Orden: {order.code}. Monto: {order.amount} {order.currency}.')
        whatsapp_url = f'https://wa.me/{academy.payment_whatsapp_number}?text={msg}'
    banks = scope_banks(BankAccount.objects.filter(is_active=True), academy) if academy.payment_transfer_enabled else BankAccount.objects.none()
    return render(request, 'billing/order.html', {
        'order': order, 'form': form, 'banks': banks, 'whatsapp_url': whatsapp_url,
        'academy': academy,
    })


@superadmin_required
def payment_proof(request, payment_id):
    course_ids = scope_courses(Course.objects.all(), request.academy).values_list('pk', flat=True)
    payment = get_object_or_404(Payment.objects.select_related('order__course'), id=payment_id, order__course_id__in=course_ids)
    if not payment.proof:
        raise Http404
    response = FileResponse(payment.proof.open('rb'))
    response['Content-Disposition'] = f'inline; filename="comprobante-{payment.order.code}"'
    response['Cache-Control'] = 'private, no-store, max-age=0'
    return response
