from io import BytesIO
from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.contrib.auth.decorators import login_required
from reportlab.lib.pagesizes import landscape, A4
from reportlab.pdfgen import canvas
import qrcode
from .models import Certificate



@login_required
def my_certificates(request):
    certificates = Certificate.objects.filter(enrollment__user=request.user).select_related('enrollment__course').order_by('-issued_at')
    return render(request, 'certificates/list.html', {'certificates': certificates})

def verify(request, code):
    certificate = get_object_or_404(Certificate.objects.select_related('enrollment__user', 'enrollment__course'), code=code)
    return render(request, 'certificates/verify.html', {'certificate': certificate})

@login_required
def certificate_pdf(request, code):
    certificate = get_object_or_404(Certificate.objects.select_related('enrollment__user', 'enrollment__course'), code=code)
    if certificate.enrollment.user_id != request.user.id and not request.user.is_superuser:
        raise Http404
    buf = BytesIO()
    page = landscape(A4)
    c = canvas.Canvas(buf, pagesize=page)
    width, height = page
    c.setTitle(f'Certificado {certificate.code}')
    c.setFont('Helvetica-Bold', 28)
    c.drawCentredString(width / 2, height - 100, 'DEVLAYER ACADEMY')
    c.setFont('Helvetica', 16)
    c.drawCentredString(width / 2, height - 145, 'CERTIFICADO DE FINALIZACIÓN')
    c.setFont('Helvetica', 13)
    c.drawCentredString(width / 2, height - 200, 'Se certifica que')
    c.setFont('Helvetica-Bold', 24)
    c.drawCentredString(width / 2, height - 240, certificate.enrollment.user.display_name)
    c.setFont('Helvetica', 13)
    c.drawCentredString(width / 2, height - 285, 'ha completado satisfactoriamente el curso')
    c.setFont('Helvetica-Bold', 20)
    c.drawCentredString(width / 2, height - 325, certificate.enrollment.course.title)
    c.setFont('Helvetica', 10)
    c.drawString(60, 70, f'Código: {certificate.code}')
    c.drawString(60, 52, f'Emitido: {certificate.issued_at.strftime("%d/%m/%Y")}')
    verify_url = f'{settings.PUBLIC_BASE_URL}/certificados/verificar/{certificate.code}/'
    qr = qrcode.make(verify_url)
    qr_buf = BytesIO()
    qr.save(qr_buf, format='PNG')
    qr_buf.seek(0)
    from reportlab.lib.utils import ImageReader
    c.drawImage(ImageReader(qr_buf), width - 145, 35, 95, 95, preserveAspectRatio=True, mask='auto')
    c.showPage()
    c.save()
    buf.seek(0)
    return FileResponse(buf, as_attachment=True, filename=f'certificado-{certificate.code}.pdf')
