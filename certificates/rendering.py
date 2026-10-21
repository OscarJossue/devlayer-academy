from io import BytesIO

import qrcode
from django.conf import settings
from django.contrib.staticfiles import finders
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .design import resolve_certificate_style


def _rgb(hex_value, fallback):
    value = (hex_value or fallback).lstrip('#')
    try:
        return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except Exception:
        value = fallback.lstrip('#')
        return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _draw_centered_fit(c, text, x, y, max_width, start_size, font='Helvetica-Bold', min_size=12):
    size = start_size
    while size > min_size and c.stringWidth(text, font, size) > max_width:
        size -= 1
    c.setFont(font, size)
    c.drawCentredString(x, y, text)


def _draw_image_field(c, image_field, x, y, width, height):
    if not image_field:
        return False
    try:
        image_field.open('rb')
        reader = ImageReader(image_field)
        c.drawImage(reader, x, y, width, height, preserveAspectRatio=True, anchor='c', mask='auto')
        image_field.close()
        return True
    except Exception:
        try:
            image_field.close()
        except Exception:
            pass
        return False


def render_certificate_pdf(academy, course, student_name, code='VISTA-PREVIA', issued_at=None):
    style = resolve_certificate_style(course, academy)
    page = landscape(A4)
    width, height = page
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=page)

    bg = _rgb(style['background_color'], '#FFFFFF')
    text = _rgb(style['text_color'], '#172033')
    accent = _rgb(style['accent_color'], '#1458D6')
    c.setFillColorRGB(*bg)
    c.rect(0, 0, width, height, fill=1, stroke=0)
    c.setFillColorRGB(*accent)
    c.rect(0, height - 12, width, 12, fill=1, stroke=0)
    c.rect(0, 0, width, 7, fill=1, stroke=0)

    if style['show_logo']:
        logo_drawn = _draw_image_field(c, academy.logo if academy.logo else None, 55, height - 110, 170, 65)
        if not logo_drawn:
            default_path = finders.find('img/devlayer-studio.png')
            if default_path:
                try:
                    c.drawImage(default_path, 55, height - 110, 170, 65, preserveAspectRatio=True, anchor='c', mask='auto')
                except Exception:
                    pass

    c.setFillColorRGB(*text)
    _draw_centered_fit(c, style['title'].upper(), width / 2, height - 105, width - 180, 28)
    c.setFont('Helvetica', 13)
    c.drawCentredString(width / 2, height - 155, style['subtitle'])
    _draw_centered_fit(c, student_name, width / 2, height - 205, width - 160, 27)
    c.setFont('Helvetica', 13)
    c.drawCentredString(width / 2, height - 248, style['body'])
    _draw_centered_fit(c, course.title, width / 2, height - 292, width - 170, 21)

    # Firma de la academia/curso.
    signature_y = 112
    if style.get('signature_image'):
        _draw_image_field(c, style['signature_image'], width / 2 - 80, signature_y + 18, 160, 55)
    if style['signature_name']:
        c.setStrokeColorRGB(*accent)
        c.line(width / 2 - 100, signature_y + 12, width / 2 + 100, signature_y + 12)
        c.setFillColorRGB(*text)
        c.setFont('Helvetica-Bold', 10)
        c.drawCentredString(width / 2, signature_y - 3, style['signature_name'])
        if style['signature_role']:
            c.setFont('Helvetica', 9)
            c.drawCentredString(width / 2, signature_y - 17, style['signature_role'])

    c.setFillColorRGB(*text)
    c.setFont('Helvetica', 8.5)
    issue_text = issued_at.strftime('%d/%m/%Y') if issued_at else 'Fecha de emisión'
    c.drawString(45, 45, f'Código: {code}')
    c.drawString(45, 31, f'Emitido: {issue_text}')
    if style['footer']:
        _draw_centered_fit(c, style['footer'], width / 2, 31, 390, 8.5, font='Helvetica', min_size=7)

    if style['show_qr']:
        verify_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/certificados/verificar/{code}/"
        qr = qrcode.make(verify_url)
        qr_buf = BytesIO()
        qr.save(qr_buf, format='PNG')
        qr_buf.seek(0)
        c.drawImage(ImageReader(qr_buf), width - 118, 28, 75, 75, preserveAspectRatio=True, mask='auto')

    c.showPage()
    c.save()
    buf.seek(0)
    return buf
