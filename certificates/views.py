from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

from core.decorators import verified_email_required
from catalog.models import Course
from tenancy.services import academy_for_course, scope_courses
from .models import Certificate
from .rendering import render_certificate_pdf


@verified_email_required
def my_certificates(request):
    course_ids = scope_courses(Course.objects.all(), request.academy).values_list('pk', flat=True)
    certificates = Certificate.objects.filter(
        enrollment__user=request.user,
        enrollment__course_id__in=course_ids,
    ).select_related('enrollment__course').order_by('-issued_at')
    if not certificates.exists() and not request.user.enrollments.filter(
        course_id__in=course_ids,
        course__certificate_enabled=True,
    ).exists():
        messages.info(request, 'Tus cursos actuales no tienen certificación habilitada.')
        return redirect('learning:my_courses')
    return render(request, 'certificates/list.html', {'certificates': certificates})


def verify(request, code):
    certificate = get_object_or_404(Certificate.objects.select_related('enrollment__user', 'enrollment__course'), code=code)
    academy = academy_for_course(certificate.enrollment.course)
    return render(request, 'certificates/verify.html', {'certificate': certificate, 'certificate_academy': academy})


@verified_email_required
def certificate_pdf(request, code):
    certificate = get_object_or_404(Certificate.objects.select_related('enrollment__user', 'enrollment__course'), code=code)
    academy = academy_for_course(certificate.enrollment.course)
    same_academy = bool(academy and request.academy and academy.pk == request.academy.pk)
    is_student_owner = certificate.enrollment.user_id == request.user.id
    is_academy_owner = getattr(request, 'academy_role', '') == 'OWNER'
    if not same_academy or not (is_student_owner or is_academy_owner):
        raise Http404
    buf = render_certificate_pdf(
        academy=academy,
        course=certificate.enrollment.course,
        student_name=certificate.enrollment.user.display_name,
        code=certificate.code,
        issued_at=certificate.issued_at,
    )
    return FileResponse(buf, as_attachment=True, filename=f'certificado-{certificate.code}.pdf')
