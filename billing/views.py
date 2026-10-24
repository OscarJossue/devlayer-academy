from urllib.parse import quote

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


def _digits(value):
    return ''.join(ch for ch in (value or '') if ch.isdigit())


def _payment_whatsapp_url(academy, order, *, purpose='proof'):
    # Los pagos jamás usan el WhatsApp interno de DevLayer Studio. El botón solo
    # aparece cuando el dueño habilitó WhatsApp o el cobro con tarjeta por link.
    if not (academy.payment_whatsapp_enabled or academy.payment_card_enabled):
        return ''
    number = (
        _digits(academy.payment_whatsapp_number)
        or _digits(academy.support_whatsapp_1_number)
        or _digits(academy.support_whatsapp_2_number)
    )
    if not number:
        return ''
    if purpose == 'card':
        msg = quote(
            f'Hola, quiero adquirir el curso {order.course.title} de {academy.name} y deseo pagar con tarjeta. '
            f'¿Me pueden ayudar con un link de pago? Orden: {order.code}. '
            f'Monto: {order.amount} {order.currency}. Mi usuario es {order.user.email}.'
        )
    elif purpose == 'advisor':
        msg = quote(
            f'Hola, estoy interesado/a en adquirir el curso {order.course.title} de {academy.name}. '
            f'Tengo una duda y prefiero realizar mi compra con ayuda de un asesor por WhatsApp. '
            f'Orden: {order.code}. Monto: {order.amount} {order.currency}. Mi usuario es {order.user.email}.'
        )
    else:
        msg = quote(
            f'Hola, deseo enviar mi comprobante de pago para {academy.name}. '
            f'Curso: {order.course.title}. Orden: {order.code}. '
            f'Monto: {order.amount} {order.currency}. Mi usuario es {order.user.email}.'
        )
    return f'https://wa.me/{number}?text={msg}'


def _external_payment_methods(academy):
    methods = []
    if academy.payment_paypal_enabled:
        methods.append({
            'code': Payment.Method.PAYPAL, 'label': 'PayPal',
            'detail': academy.payment_paypal_email or 'Cuenta PayPal de la academia',
            'url': academy.payment_paypal_url,
        })
    if academy.payment_payphone_enabled:
        methods.append({
            'code': Payment.Method.PAYPHONE, 'label': 'PayPhone',
            'detail': academy.payment_payphone_reference or 'Cuenta PayPhone de la academia',
            'url': academy.payment_payphone_url,
        })
    for index in (1, 2):
        if getattr(academy, f'payment_link_{index}_enabled'):
            methods.append({
                'code': Payment.Method.PAYMENT_LINK,
                'label': getattr(academy, f'payment_link_{index}_label') or f'Link de pago {index}',
                'detail': 'Pago online seguro',
                'url': getattr(academy, f'payment_link_{index}_url'),
            })
    return methods


@verified_email_required
def history(request):
    course_ids = scope_courses(Course.objects.all(), request.academy).values_list('pk', flat=True)
    orders = list(
        Order.objects.filter(user=request.user, course_id__in=course_ids)
        .select_related('course', 'user')
        .prefetch_related('payments')
        .order_by('-created_at')
    )
    for order in orders:
        order.student_whatsapp_url = _payment_whatsapp_url(request.academy, order)
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
    order = get_object_or_404(Order.objects.select_related('course', 'user'), id=order_id, user=request.user, course_id__in=course_ids)
    enrollment = Enrollment.objects.filter(user=request.user, course=order.course).first()
    if enrollment and enrollment.access_allowed():
        messages.info(request, 'Este curso ya está habilitado en tu cuenta.')
        return redirect('catalog:course_detail', slug=order.course.slug)
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
    whatsapp_url = _payment_whatsapp_url(academy, order)
    advisor_whatsapp_url = _payment_whatsapp_url(academy, order, purpose='advisor')
    card_whatsapp_url = _payment_whatsapp_url(academy, order, purpose='card') if academy.payment_card_enabled else ''
    banks = scope_banks(BankAccount.objects.filter(is_active=True), academy) if academy.payment_transfer_enabled else BankAccount.objects.none()
    return render(request, 'billing/order.html', {
        'order': order, 'form': form, 'banks': banks, 'whatsapp_url': whatsapp_url,
        'advisor_whatsapp_url': advisor_whatsapp_url, 'card_whatsapp_url': card_whatsapp_url,
        'external_methods': _external_payment_methods(academy),
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
