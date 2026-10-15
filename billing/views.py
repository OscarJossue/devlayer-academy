from urllib.parse import quote
from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from core.decorators import verified_email_required
from catalog.models import Course
from learning.models import Enrollment
from learning.services import create_or_activate_enrollment
from .forms import PaymentProofForm
from .models import BankAccount, Order, Payment


@verified_email_required
def history(request):
    orders = Order.objects.filter(user=request.user).select_related('course').prefetch_related('payments').order_by('-created_at')
    return render(request, 'billing/history.html', {'orders': orders})

@verified_email_required
def checkout(request, course_slug):
    course = get_object_or_404(Course, slug=course_slug, status__in=[Course.Status.APPROVED, Course.Status.PUBLISHED])
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
    order = get_object_or_404(Order, id=order_id, user=request.user)
    payment = order.payments.filter(status=Payment.Status.PENDING).order_by('-created_at').first()
    form = PaymentProofForm(request.POST or None, request.FILES or None, instance=payment)
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        obj.order = order
        obj.amount = order.amount
        obj.status = Payment.Status.PENDING
        obj.save()
        messages.success(request, 'Comprobante registrado. Se habilitará el curso al aprobar el pago.')
        return redirect('billing:order', order.id)
    whatsapp_url = ''
    if settings.WHATSAPP_NUMBER:
        msg = quote(f'Hola, deseo reportar el pago del curso {order.course.title}. Orden: {order.code}. Monto: {order.amount} {order.currency}.')
        whatsapp_url = f'https://wa.me/{settings.WHATSAPP_NUMBER}?text={msg}'
    return render(request, 'billing/order.html', {
        'order': order, 'form': form, 'banks': BankAccount.objects.filter(is_active=True), 'whatsapp_url': whatsapp_url,
    })

from django.contrib.auth.decorators import user_passes_test
from django.http import FileResponse, Http404

@user_passes_test(lambda u: u.is_superuser)
def payment_proof(request, payment_id):
    payment = get_object_or_404(Payment, id=payment_id)
    if not payment.proof:
        raise Http404
    response = FileResponse(payment.proof.open('rb'))
    response['Content-Disposition'] = f'inline; filename="comprobante-{payment.order.code}"'
    response['Cache-Control'] = 'private, no-store, max-age=0'
    return response
