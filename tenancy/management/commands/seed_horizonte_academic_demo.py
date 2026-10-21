from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from assessments.models import Choice, Question, Quiz
from catalog.models import Category, Course, CourseInstructor, Lesson, Module
from catalog.pdf_tools import PDFMaterialError, optimize_pdf_bytes
from tenancy.models import Academy, AcademyMembership
from tenancy.services import bind_category, bind_course, bind_user

User = get_user_model()

VIDEO_URLS = [
    'https://www.youtube.com/watch?v=3CxtK7-XtE0&list=RDGMEMHDXYb1_DDSgDsobPsOFxpAVM3CxtK7-XtE0&start_radio=1',
    'https://www.youtube.com/watch?v=NaoNcERVF78&list=RDNaoNcERVF78&start_radio=1',
    'https://www.youtube.com/watch?v=RmfkBAmetHI&list=RDNaoNcERVF78&index=2',
    'https://www.youtube.com/watch?v=DsFYcJD9Y0k&list=RDNaoNcERVF78&index=5',
]

PROFESSORS = [
    {
        'email': 'profesor.comercio@demo.local',
        'password': 'Comercio2026!',
        'first_name': 'Daniel',
        'last_name': 'Mora',
    },
    {
        'email': 'profesor.marketing@demo.local',
        'password': 'Marketing2026!',
        'first_name': 'Sofía',
        'last_name': 'Vega',
    },
]


def _attach_static(field_file, relative_source, storage_name):
    source = Path(settings.BASE_DIR) / 'static' / relative_source
    if not source.exists():
        raise CommandError(f'No se encontró el recurso demo: {source}')
    data = source.read_bytes()
    if source.suffix.lower() == '.pdf':
        try:
            data, _ = optimize_pdf_bytes(data, source.name)
        except PDFMaterialError as exc:
            raise CommandError(f'No se pudo optimizar {source.name}: {exc}') from exc
    storage = field_file.storage
    if storage.exists(storage_name):
        storage.delete(storage_name)
    saved = storage.save(storage_name, ContentFile(data))
    field_file.name = saved


def _question(quiz, order, text, qtype, options=None, correct=None, explanation=''):
    question, _ = Question.objects.update_or_create(
        quiz=quiz,
        order=order,
        defaults={
            'text': text,
            'question_type': qtype,
            'explanation': explanation,
            'is_active': True,
        },
    )
    question.choices.all().delete()
    options = options or []
    correct = set(correct or [])
    for idx, option in enumerate(options, start=1):
        Choice.objects.create(
            question=question,
            text=option,
            is_correct=idx in correct,
            order=idx,
        )
    return question


def _module_quiz(course, module, title, questions, pass_percentage=70, max_attempts=3, open_review=False):
    quiz, _ = Quiz.objects.update_or_create(
        course=course,
        module=module,
        kind=Quiz.Kind.MODULE,
        defaults={
            'title': title,
            'question_count': len(questions),
            'pass_percentage': pass_percentage,
            'max_attempts': max_attempts,
            'show_correct_answers': True,
            'randomize_questions': False,
            'randomize_choices': True,
            'is_required': True,
            'is_active': True,
        },
    )
    for idx, row in enumerate(questions, start=1):
        _question(quiz, idx, **row)
    quiz.questions.exclude(order__lte=len(questions)).delete()
    return quiz


class Command(BaseCommand):
    help = 'Crea dos profesores y dos cursos completos de demostración en Academia Horizonte.'

    @transaction.atomic
    def handle(self, *args, **options):
        academy = Academy.objects.select_related('license').filter(slug='academia-horizonte').first()
        if not academy:
            raise CommandError('Primero crea la academia demo “academia-horizonte” con seed_platform_demo o reset_platform --demo.')
        if not academy.access_enabled:
            raise CommandError('Academia Horizonte existe, pero su licencia no está activa.')

        owner_membership = AcademyMembership.objects.filter(
            academy=academy,
            role=AcademyMembership.Role.OWNER,
            status=AcademyMembership.Status.ACTIVE,
        ).first()
        owner = User.objects.filter(pk=owner_membership.user_id).first() if owner_membership else None
        if not owner:
            raise CommandError('Academia Horizonte no tiene un dueño activo.')

        professors = []
        for data in PROFESSORS:
            user, _ = User.objects.get_or_create(
                email=data['email'],
                defaults={
                    'first_name': data['first_name'],
                    'last_name': data['last_name'],
                    'role': User.Role.PROFESSOR,
                    'email_verified': True,
                    'is_active': True,
                },
            )
            user.first_name = data['first_name']
            user.last_name = data['last_name']
            user.role = User.Role.PROFESSOR
            user.email_verified = True
            user.is_active = True
            user.set_password(data['password'])
            user.save()
            bind_user(user, academy, role=AcademyMembership.Role.PROFESSOR, status=AcademyMembership.Status.ACTIVE, approved_by=owner)
            professors.append(user)

        commerce_category, _ = Category.objects.update_or_create(
            slug='comercio-digital-horizonte',
            defaults={
                'name': 'Comercio Digital',
                'description': 'E-commerce, ventas en línea y operación de tiendas digitales.',
                'is_active': True,
                'order': 10,
            },
        )
        marketing_category, _ = Category.objects.update_or_create(
            slug='marketing-digital-horizonte',
            defaults={
                'name': 'Marketing Digital',
                'description': 'Captación, embudos, seguimiento y optimización de conversiones.',
                'is_active': True,
                'order': 20,
            },
        )
        bind_category(commerce_category, academy)
        bind_category(marketing_category, academy)

        now = timezone.now()
        course1, _ = Course.objects.update_or_create(
            slug='ecommerce-tienda-digital-horizonte',
            defaults={
                'title': 'E-commerce: crea y optimiza tu tienda digital',
                'short_description': 'Aprende a estructurar una tienda, organizar el catálogo, configurar confianza y medir la conversión.',
                'description': (
                    'Construye la base de una tienda digital clara y orientada a resultados. '
                    'Aprenderás a definir la propuesta de valor, organizar el catálogo, mejorar la experiencia móvil, '
                    'preparar pagos y confianza, y revisar las métricas básicas del proceso de compra.\n\n'
                    'Ideal para validar el flujo completo de Academy: video, material protegido en diapositivas, cuestionarios automáticos, examen final y certificado.'
                ),
                'category': commerce_category,
                'price': 39,
                'currency': 'USD',
                'status': Course.Status.PUBLISHED,
                'sequential_learning': True,
                'default_pass_percentage': 70,
                'access_type': Course.AccessType.PERMANENT,
                'post_certificate_policy': Course.PostCertificatePolicy.KEEP,
                'final_exam_required': True,
                'certificate_enabled': True,
                'certificate_style_mode': Course.CertificateStyleMode.ACADEMY,
                'masterclass_enabled': True,
                'masterclass_title': 'Clase magistral · E-commerce en acción',
                'masterclass_description': 'Repaso final del curso, pautas prácticas para aplicar lo aprendido y espacio abierto para preguntas y resolución de dudas.',
                'masterclass_meeting_url': 'https://meet.google.com/',
                'masterclass_scheduled_at': now + timedelta(days=7),
                'masterclass_duration_minutes': 60,
                'created_by': professors[0],
                'approved_by': owner,
                'approved_at': now,
                'published_at': now,
            },
        )
        bind_course(course1, academy)
        CourseInstructor.objects.update_or_create(course=course1, user=professors[0], defaults={'is_owner': True})
        _attach_static(course1.thumbnail, 'demo/course_covers/ecommerce-horizonte.webp', 'course_thumbnails/demo/horizonte-ecommerce.webp')
        course1.save(update_fields=['thumbnail', 'updated_at'])

        m11, _ = Module.objects.update_or_create(
            course=course1, order=1,
            defaults={
                'title': 'Fundamentos de una tienda que convierte',
                'description': 'Aprende a definir la propuesta de valor, organizar el catálogo y diseñar una experiencia de compra clara, especialmente en móvil.',
                'is_published': True,
                'requires_quiz_to_unlock_next': True,
            },
        )
        l11, _ = Lesson.objects.update_or_create(
            module=m11, order=1,
            defaults={
                'title': 'Diseña una tienda que el cliente entienda',
                'description': 'Revisa propuesta de valor, jerarquía del catálogo, ficha de producto y puntos de fricción antes de llevar al usuario al pago.',
                'duration_minutes': 18,
                'video_provider': Lesson.VideoProvider.YOUTUBE,
                'video_source': VIDEO_URLS[0],
                'is_preview': False,
                'is_published': True,
            },
        )
        _attach_static(l11.material_pdf, 'demo/materials/ecommerce-modulo-1.pdf', 'private/materials/demo/horizonte/ecommerce-modulo-1.pdf')
        l11.description = (l11.description or '').split('Contenido extraído del material PDF:', 1)[0].strip()
        l11.save(update_fields=['material_pdf', 'description'])
        _module_quiz(course1, m11, 'Cuestionario · Fundamentos del e-commerce', [
            {'text': '¿Qué debe comunicar una propuesta de valor?', 'qtype': Question.Type.SINGLE, 'options': ['Para quién es la oferta y qué problema resuelve', 'Solo el nombre de la empresa', 'Únicamente el precio', 'La cantidad de menús'], 'correct': [1]},
            {'text': 'Selecciona elementos útiles en una ficha de producto.', 'qtype': Question.Type.MULTIPLE, 'options': ['Beneficios', 'Precio', 'Disponibilidad', 'Texto sin relación'], 'correct': [1,2,3]},
            {'text': '¿Qué efecto puede tener una navegación móvil simple?', 'qtype': Question.Type.SINGLE, 'options': ['Reducir fricción en la compra', 'Aumentar pasos innecesarios', 'Ocultar productos', 'Eliminar el checkout'], 'correct': [1]},
            {'text': '¿Cuál es una buena práctica para el catálogo?', 'qtype': Question.Type.SINGLE, 'options': ['Categorías claras y consistentes', 'Duplicar productos', 'Ocultar disponibilidad', 'Eliminar búsqueda'], 'correct': [1]},
            {'text': 'Selecciona acciones que aumentan la confianza antes del pago.', 'qtype': Question.Type.MULTIPLE, 'options': ['Mostrar políticas claras', 'Mostrar métodos de pago', 'Incluir contacto visible', 'Ocultar condiciones'], 'correct': [1,2,3]},
        ])

        m12, _ = Module.objects.update_or_create(
            course=course1, order=2,
            defaults={
                'title': 'Operación, pago y conversión',
                'description': 'Configura una experiencia de pago confiable, organiza el seguimiento postventa y aprende a detectar dónde se pierde la conversión.',
                'is_published': True,
                'requires_quiz_to_unlock_next': True,
            },
        )
        l12, _ = Lesson.objects.update_or_create(
            module=m12, order=1,
            defaults={
                'title': 'Convierte visitas en pedidos y clientes recurrentes',
                'description': 'Conecta métodos de pago, mensajes de confianza, confirmación de pedidos, soporte y métricas básicas de checkout.',
                'duration_minutes': 22,
                'video_provider': Lesson.VideoProvider.YOUTUBE,
                'video_source': VIDEO_URLS[1],
                'is_preview': False,
                'is_published': True,
            },
        )
        _attach_static(l12.material_pdf, 'demo/materials/ecommerce-modulo-2.pdf', 'private/materials/demo/horizonte/ecommerce-modulo-2.pdf')
        l12.description = (l12.description or '').split('Contenido extraído del material PDF:', 1)[0].strip()
        l12.save(update_fields=['material_pdf', 'description'])
        _module_quiz(course1, m12, 'Cuestionario · Operación y conversión', [
            {'text': '¿Qué información reduce dudas antes del pago?', 'qtype': Question.Type.MULTIPLE, 'options': ['Métodos de pago', 'Tiempos de entrega', 'Políticas', 'Campos ocultos'], 'correct': [1,2,3]},
            {'text': '¿Qué comparación ayuda a detectar abandono?', 'qtype': Question.Type.SINGLE, 'options': ['Inicios de checkout vs compras', 'Colores vs fuentes', 'Logo vs favicon', 'Cantidad de menús'], 'correct': [1]},
            {'text': '¿Qué puede favorecer la recompra después de una venta?', 'qtype': Question.Type.SINGLE, 'options': ['Una buena postventa', 'Eliminar soporte', 'No confirmar pedidos', 'Ocultar el estado'], 'correct': [1]},
            {'text': '¿Qué debe ocurrir después de una compra?', 'qtype': Question.Type.SINGLE, 'options': ['Confirmar la orden y comunicar el estado', 'Cerrar todos los canales', 'Eliminar el pedido', 'Ocultar soporte'], 'correct': [1]},
            {'text': 'Selecciona métricas útiles para mejorar el checkout.', 'qtype': Question.Type.MULTIPLE, 'options': ['Tasa de abandono', 'Conversión a compra', 'Errores de pago', 'Color favorito del equipo'], 'correct': [1,2,3]},
        ])

        final1, _ = Quiz.objects.update_or_create(
            course=course1,
            module=None,
            kind=Quiz.Kind.FINAL,
            defaults={
                'title': 'Examen final · E-commerce',
                'question_count': 6,
                'pass_percentage': 70,
                'max_attempts': 3,
                'show_correct_answers': True,
                'randomize_questions': False,
                'randomize_choices': True,
                'is_required': True,
                'is_active': True,
            },
        )
        final_questions = [
            {'text': '¿Qué conecta una propuesta de valor?', 'qtype': Question.Type.SINGLE, 'options': ['Cliente, problema y beneficio', 'Solo colores', 'Solo precio', 'Solo inventario'], 'correct': [1]},
            {'text': 'Selecciona señales de confianza antes del checkout.', 'qtype': Question.Type.MULTIPLE, 'options': ['Políticas claras', 'Métodos de pago visibles', 'Contacto disponible', 'Errores ocultos'], 'correct': [1,2,3]},
            {'text': '¿Qué elemento forma parte de la conversión en una tienda digital?', 'qtype': Question.Type.SINGLE, 'options': ['La experiencia móvil', 'Solo el favicon', 'Solo el nombre del archivo', 'Solo la hora de publicación'], 'correct': [1]},
            {'text': '¿Qué dato indica una pérdida entre checkout y compra?', 'qtype': Question.Type.SINGLE, 'options': ['La diferencia entre ambos volúmenes', 'El nombre del dominio', 'El tamaño del logo', 'El número de categorías'], 'correct': [1]},
            {'text': '¿Qué acción es adecuada tras una compra?', 'qtype': Question.Type.SINGLE, 'options': ['Confirmar y dar seguimiento', 'Eliminar el pedido', 'No responder', 'Ocultar soporte'], 'correct': [1]},
            {'text': '¿Qué ayuda a mejorar de forma controlada?', 'qtype': Question.Type.SINGLE, 'options': ['Cambiar una variable importante y medir', 'Cambiar todo al mismo tiempo', 'No medir', 'Duplicar errores'], 'correct': [1]},
        ]
        for idx, row in enumerate(final_questions, start=1):
            _question(final1, idx, **row)
        final1.questions.exclude(order__lte=len(final_questions)).delete()

        course2, _ = Course.objects.update_or_create(
            slug='marketing-embudos-conversion-horizonte',
            defaults={
                'title': 'Marketing Digital: embudos y conversión',
                'short_description': 'Diseña mensajes, canales y un embudo sencillo para captar, seguir y convertir oportunidades.',
                'description': (
                    'Organiza una estrategia digital sencilla alrededor de una audiencia concreta. '
                    'Aprenderás a construir mensajes, elegir canales, estructurar un embudo, registrar el seguimiento y revisar conversiones.\n\n'
                    'Este curso demo no genera certificado: sirve para validar que Academy finaliza correctamente cursos con y sin certificación.'
                ),
                'category': marketing_category,
                'price': 29,
                'currency': 'USD',
                'status': Course.Status.PUBLISHED,
                'sequential_learning': True,
                'default_pass_percentage': 70,
                'access_type': Course.AccessType.PERMANENT,
                'post_certificate_policy': Course.PostCertificatePolicy.KEEP,
                'final_exam_required': False,
                'certificate_enabled': False,
                'certificate_style_mode': Course.CertificateStyleMode.ACADEMY,
                'masterclass_enabled': False,
                'masterclass_title': 'Clase magistral · Embudos y conversión',
                'masterclass_description': 'Repaso del embudo, revisión de casos y espacio para preguntas de implementación.',
                'masterclass_meeting_url': '',
                'masterclass_scheduled_at': None,
                'masterclass_duration_minutes': 60,
                'created_by': professors[1],
                'approved_by': owner,
                'approved_at': now,
                'published_at': now,
            },
        )
        bind_course(course2, academy)
        CourseInstructor.objects.update_or_create(course=course2, user=professors[1], defaults={'is_owner': True})
        _attach_static(course2.thumbnail, 'demo/course_covers/marketing-horizonte.webp', 'course_thumbnails/demo/horizonte-marketing.webp')
        course2.save(update_fields=['thumbnail', 'updated_at'])

        m21, _ = Module.objects.update_or_create(
            course=course2, order=1,
            defaults={
                'title': 'Audiencia, mensaje y captación',
                'description': 'Define una audiencia concreta, construye un mensaje claro y elige canales de captación que puedas medir y operar.',
                'is_published': True,
                'requires_quiz_to_unlock_next': True,
            },
        )
        l21, _ = Lesson.objects.update_or_create(
            module=m21, order=1,
            defaults={
                'title': 'Construye un mensaje que atraiga al cliente correcto',
                'description': 'Relaciona problema, beneficio, prueba y llamada a la acción para mantener coherencia entre anuncio, página y contacto.',
                'duration_minutes': 19,
                'video_provider': Lesson.VideoProvider.YOUTUBE,
                'video_source': VIDEO_URLS[2],
                'is_preview': False,
                'is_published': True,
            },
        )
        _attach_static(l21.material_pdf, 'demo/materials/marketing-modulo-1.pdf', 'private/materials/demo/horizonte/marketing-modulo-1.pdf')
        l21.save(update_fields=['material_pdf'])
        _module_quiz(course2, m21, 'Cuestionario · Atracción y mensajes', [
            {'text': '¿Qué debería incluir una definición básica de audiencia?', 'qtype': Question.Type.MULTIPLE, 'options': ['Necesidad', 'Objeciones', 'Resultado deseado', 'Datos irrelevantes'], 'correct': [1,2,3]},
            {'text': '¿Qué conecta un mensaje claro?', 'qtype': Question.Type.SINGLE, 'options': ['Problema, beneficio, prueba y acción', 'Solo el logo', 'Solo el precio', 'Solo la plataforma'], 'correct': [1]},
            {'text': '¿Cuál es la mejor decisión al elegir canales de captación?', 'qtype': Question.Type.SINGLE, 'options': ['Elegir canales que puedas operar y medir', 'Abrir todos sin medir', 'No definir objetivos', 'Evitar registrar resultados'], 'correct': [1]},
            {'text': '¿Cuál es una buena práctica de captación?', 'qtype': Question.Type.SINGLE, 'options': ['Elegir canales según intención y capacidad', 'Copiar todos los canales', 'No definir acción', 'No medir'], 'correct': [1]},
            {'text': '¿Qué debe mantenerse coherente entre anuncio y página?', 'qtype': Question.Type.SINGLE, 'options': ['La promesa principal', 'Solo el tamaño de fuente', 'El navegador', 'La hora'], 'correct': [1]},
        ])

        m22, _ = Module.objects.update_or_create(
            course=course2, order=2,
            defaults={
                'title': 'Embudo, seguimiento y optimización',
                'description': 'Organiza etapas del embudo, estados del lead y una rutina simple de medición para detectar dónde mejorar la conversión.',
                'is_published': True,
                'requires_quiz_to_unlock_next': True,
            },
        )
        l22, _ = Lesson.objects.update_or_create(
            module=m22, order=1,
            defaults={
                'title': 'Convierte contactos en oportunidades medibles',
                'description': 'Define etapas, próximas acciones y métricas para que el seguimiento comercial pueda mejorarse con datos.',
                'duration_minutes': 24,
                'video_provider': Lesson.VideoProvider.YOUTUBE,
                'video_source': VIDEO_URLS[3],
                'is_preview': False,
                'is_published': True,
            },
        )
        _attach_static(l22.material_pdf, 'demo/materials/marketing-modulo-2.pdf', 'private/materials/demo/horizonte/marketing-modulo-2.pdf')
        l22.save(update_fields=['material_pdf'])
        _module_quiz(course2, m22, 'Cuestionario · Embudo y optimización', [
            {'text': '¿Qué representa una etapa de embudo?', 'qtype': Question.Type.SINGLE, 'options': ['Un momento del proceso con acción y métrica', 'Un color del sitio', 'Un archivo PDF', 'Una contraseña'], 'correct': [1]},
            {'text': 'Selecciona datos útiles para seguimiento.', 'qtype': Question.Type.MULTIPLE, 'options': ['Fuente', 'Estado', 'Próxima acción', 'Dato aleatorio'], 'correct': [1,2,3]},
            {'text': '¿Qué práctica ayuda a interpretar mejor una optimización?', 'qtype': Question.Type.SINGLE, 'options': ['Cambiar una variable importante a la vez', 'Cambiar todo simultáneamente', 'No medir resultados', 'Duplicar campañas sin control'], 'correct': [1]},
            {'text': '¿Qué conviene medir por etapa?', 'qtype': Question.Type.SINGLE, 'options': ['Conversión', 'Color favorito', 'Resolución de pantalla solamente', 'Nombre del archivo'], 'correct': [1]},
            {'text': '¿Qué puede afectar la conversión de leads?', 'qtype': Question.Type.SINGLE, 'options': ['Velocidad y consistencia del seguimiento', 'Solo el logo', 'La extensión del dominio', 'El nombre del PDF'], 'correct': [1]},
        ])
        Quiz.objects.filter(course=course2, kind=Quiz.Kind.FINAL).delete()

        self.stdout.write(self.style.SUCCESS('Academia Horizonte lista: 2 profesores + 2 cursos publicados + 4 módulos + evaluaciones automáticas + materiales protegidos.'))
        self.stdout.write('Profesores demo:')
        for data in PROFESSORS:
            self.stdout.write(f"  {data['email']} / {data['password']}")
