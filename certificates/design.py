from django.templatetags.static import static


def resolve_certificate_style(course, academy):
    """Devuelve un diseño listo para vista previa/PDF, con herencia academia -> curso."""
    accent = (academy.certificate_accent_color or academy.brand_color or '#1458D6').upper()
    style = {
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
    if course and getattr(course, 'certificate_style_mode', 'ACADEMY') == 'CUSTOM':
        mapping = {
            'title': course.certificate_custom_title,
            'subtitle': course.certificate_custom_subtitle,
            'body': course.certificate_custom_body,
            'accent_color': course.certificate_custom_accent_color,
            'background_color': course.certificate_custom_background_color,
            'text_color': course.certificate_custom_text_color,
            'signature_name': course.certificate_custom_signature_name,
            'signature_role': course.certificate_custom_signature_role,
            'footer': course.certificate_custom_footer,
        }
        for key, value in mapping.items():
            if value:
                style[key] = value.upper() if 'color' in key else value
        if course.certificate_custom_signature_image:
            style['signature_image'] = course.certificate_custom_signature_image
        style['show_qr'] = bool(course.certificate_custom_show_qr)
        style['show_logo'] = bool(course.certificate_custom_show_logo)
        style['source'] = 'CUSTOM'
    return style


def preview_style_context(course, academy):
    style = resolve_certificate_style(course, academy)
    style['student_name'] = 'Nombre del estudiante'
    style['course_name'] = course.title if course else 'Nombre del curso'
    style['academy_name'] = academy.name
    style['logo_url'] = static('img/devlayer-studio.png')
    return style
