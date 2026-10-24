from django.templatetags.static import static


def resolve_certificate_style(course, academy):
    """Devuelve el diseño definido exclusivamente por el dueño de la academia.

    El curso solo decide si entrega certificado. Colores, textos, firma, logo y
    QR son configuración global de la academia para mantener consistencia y
    evitar que un profesor cambie la identidad institucional.
    """
    accent = (academy.certificate_accent_color or academy.brand_color or '#1458D6').upper()
    return {
        'title': academy.certificate_title or 'Certificado de finalización',
        'subtitle': academy.certificate_subtitle or 'Se certifica que',
        'body': academy.certificate_body or 'ha completado satisfactoriamente el curso',
        'accent_color': accent,
        'background_color': (academy.certificate_background_color or '#FFFFFF').upper(),
        'text_color': (academy.certificate_text_color or '#172033').upper(),
        'signature_name': academy.certificate_signature_name or '',
        'signature_role': academy.certificate_signature_role or '',
        'signature_image': academy.certificate_signature_image if academy.certificate_signature_image else None,
        'footer': academy.certificate_footer or '',
        'show_qr': bool(academy.certificate_show_qr),
        'show_logo': bool(academy.certificate_show_logo),
        'source': 'ACADEMY',
    }


def preview_style_context(course, academy):
    style = resolve_certificate_style(course, academy)
    style['student_name'] = 'Nombre del estudiante'
    style['course_name'] = course.title if course else 'Nombre del curso'
    style['academy_name'] = academy.name
    style['logo_url'] = static('img/devlayer-studio.png')
    return style
