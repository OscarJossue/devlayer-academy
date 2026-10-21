from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from accounts.models import User
from assessments.models import Choice, Question, Quiz
from billing.models import BankAccount
from catalog.models import Category, Course, CourseInstructor, Lesson, Module


def attach_static_cover(course, relative_path):
    if course.thumbnail:
        return
    path = Path(settings.BASE_DIR) / 'static' / relative_path
    if path.exists():
        course.thumbnail.save(path.name, ContentFile(path.read_bytes()), save=True)


def add_question(quiz, order, text, qtype, options=None, correct=None, explanation=''):
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
    correct = set(correct or [])
    for idx, option in enumerate(options or [], start=1):
        Choice.objects.create(question=question, text=option, order=idx, is_correct=idx in correct)
    return question



class Command(BaseCommand):
    help = 'Crea datos demo idempotentes para desarrollo y pruebas.'

    def handle(self, *args, **kwargs):
        admin = User.objects.filter(is_superuser=True).first()
        if not admin:
            self.stdout.write('Sin superadmin; demo omitida.')
            return

        cat_web, _ = Category.objects.get_or_create(name='Desarrollo Web', defaults={'slug': 'desarrollo-web', 'order': 1})
        cat_ai, _ = Category.objects.get_or_create(name='Inteligencia Artificial', defaults={'slug': 'inteligencia-artificial', 'order': 2})
        cat_marketing, _ = Category.objects.get_or_create(name='Marketing Digital', defaults={'slug': 'marketing-digital', 'order': 3})

        # Curso principal completo para probar todo el flujo académico.
        course, _ = Course.objects.get_or_create(
            slug='desarrollo-web-profesional-demo',
            defaults={
                'title': 'Desarrollo Web Profesional',
                'short_description': 'HTML, CSS responsive y JavaScript en una ruta práctica con evaluaciones por módulo y examen final.',
                'description': 'Curso demostrativo completo para probar módulos, clases, progreso secuencial, cuestionarios, evaluaciones automáticas y certificación.',
                'category': cat_web,
                'price': 39,
                'currency': 'USD',
                'created_by': admin,
                'status': Course.Status.PUBLISHED,
                'sequential_learning': True,
                'default_pass_percentage': 70,
                'final_exam_required': True,
                'post_certificate_policy': Course.PostCertificatePolicy.KEEP,
            },
        )
        if course.status != Course.Status.PUBLISHED:
            course.status = Course.Status.PUBLISHED
            course.save(update_fields=['status', 'updated_at'])
        CourseInstructor.objects.get_or_create(course=course, user=admin, defaults={'is_owner': True})
        attach_static_cover(course, 'img/cursos-demo/curso-ia.png')

        module_specs = [
            (1, 'Fundamentos del desarrollo web', 'Comprende cómo funciona la web y construye HTML semántico.', [
                ('Cómo funciona la web', 12, 'Cliente, servidor, navegador, URL y ciclo de una petición HTTP.'),
                ('HTML semántico', 18, 'Estructura correcta de documentos, etiquetas semánticas y buenas prácticas.'),
                ('Formularios y accesibilidad', 16, 'Inputs, labels, validación básica y accesibilidad.'),
            ]),
            (2, 'CSS y diseño responsive', 'Construye layouts claros, adaptables y mantenibles.', [
                ('Modelo de caja y selectores', 17, 'Box model, cascada, especificidad y organización de estilos.'),
                ('Flexbox y Grid', 22, 'Distribuciones modernas con Flexbox y CSS Grid.'),
                ('Responsive design', 20, 'Breakpoints, unidades fluidas y estrategia mobile first.'),
            ]),
            (3, 'JavaScript para interfaces', 'Agrega interacción real al frontend.', [
                ('Variables, funciones y eventos', 21, 'Fundamentos de JavaScript aplicados a interfaces.'),
                ('DOM y componentes', 24, 'Selección, modificación del DOM y componentes simples.'),
                ('Proyecto final', 30, 'Construcción de una landing responsive e interactiva.'),
            ]),
        ]

        for module_order, title, description, lessons in module_specs:
            module, _ = Module.objects.get_or_create(
                course=course,
                order=module_order,
                defaults={'title': title, 'description': description, 'requires_quiz_to_unlock_next': True, 'is_published': True},
            )
            if module.title != title or module.description != description:
                module.title = title
                module.description = description
                module.requires_quiz_to_unlock_next = True
                module.is_published = True
                module.save()
            for lesson_order, lesson_title, minutes, lesson_desc in [(i + 1, *spec) for i, spec in enumerate(lessons)]:
                Lesson.objects.update_or_create(
                    module=module,
                    order=lesson_order,
                    defaults={
                        'title': lesson_title,
                        'description': lesson_desc,
                        'duration_minutes': minutes,
                        'video_provider': Lesson.VideoProvider.NONE,
                        'is_preview': module_order == 1 and lesson_order == 1,
                        'is_published': True,
                    },
                )

            quiz, _ = Quiz.objects.get_or_create(
                course=course,
                module=module,
                kind=Quiz.Kind.MODULE,
                defaults={
                    'title': f'Cuestionario · {title}',
                    'question_count': 5,
                    'pass_percentage': 70,
                    'max_attempts': 3,
                    'randomize_questions': True,
                    'randomize_choices': True,
                    'is_required': True,
                    'is_active': True,
                },
            )
            if module_order == 1:
                add_question(quiz, 1, '¿Qué etiqueta HTML representa el contenido principal?', Question.Type.SINGLE, ['<main>', '<span>', '<aside>', '<meta>'], [1])
                add_question(quiz, 2, 'Selecciona elementos semánticos de HTML.', Question.Type.MULTIPLE, ['<article>', '<section>', '<nav>', '<font>'], [1, 2, 3])
                add_question(quiz, 3, 'El atributo for de un label puede relacionarse con el id de un input.', Question.Type.SINGLE, ['Verdadero', 'Falso'], [1])
                add_question(quiz, 4, 'Selecciona beneficios del HTML semántico.', Question.Type.MULTIPLE, ['Mejora accesibilidad', 'Facilita mantenimiento', 'Da estructura al contenido', 'Elimina la necesidad de CSS'], [1, 2, 3])
                add_question(quiz, 5, '¿Qué protocolo se usa normalmente para servir páginas web seguras?', Question.Type.SINGLE, ['FTP', 'HTTPS', 'SMTP', 'SSH'], [2])
                add_question(quiz, 6, '¿Qué elemento representa navegación principal?', Question.Type.SINGLE, ['<nav>', '<b>', '<script>', '<br>'], [1])
            elif module_order == 2:
                add_question(quiz, 1, '¿Qué propiedad define columnas en CSS Grid?', Question.Type.SINGLE, ['grid-template-columns', 'flex-direction', 'column-mode', 'layout-columns'], [1])
                add_question(quiz, 2, 'Selecciona propiedades de Flexbox.', Question.Type.MULTIPLE, ['justify-content', 'align-items', 'flex-direction', 'grid-area'], [1, 2, 3])
                add_question(quiz, 3, 'Mobile first comienza diseñando para pantallas pequeñas.', Question.Type.SINGLE, ['Verdadero', 'Falso'], [1])
                add_question(quiz, 4, 'Selecciona estrategias para evitar desbordes en tarjetas responsive.', Question.Type.MULTIPLE, ['Usar max-width', 'Permitir ajuste de texto', 'Probar anchos pequeños', 'Forzar anchos fijos enormes'], [1, 2, 3])
                add_question(quiz, 5, '¿Qué unidad es relativa al tamaño de fuente raíz?', Question.Type.SINGLE, ['px', 'rem', 'vh', 'cm'], [2])
                add_question(quiz, 6, '¿Cuál propiedad controla el espacio interno?', Question.Type.SINGLE, ['margin', 'padding', 'gap-only', 'border'], [2])
            else:
                add_question(quiz, 1, '¿Qué método selecciona el primer elemento por selector CSS?', Question.Type.SINGLE, ['querySelector', 'findElement', 'selectNode', 'getOne'], [1])
                add_question(quiz, 2, 'Selecciona eventos comunes del DOM.', Question.Type.MULTIPLE, ['click', 'submit', 'change', 'compile'], [1, 2, 3])
                add_question(quiz, 3, 'addEventListener permite escuchar eventos del navegador.', Question.Type.SINGLE, ['Verdadero', 'Falso'], [1])
                add_question(quiz, 4, 'Selecciona buenas prácticas para separar JavaScript y CSS.', Question.Type.MULTIPLE, ['Usar clases para estados visuales', 'Mantener estilos en CSS', 'Usar eventos en JavaScript', 'Escribir todo el CSS dentro de cada evento'], [1, 2, 3])
                add_question(quiz, 5, '¿Qué objeto representa el documento HTML?', Question.Type.SINGLE, ['document', 'windowStyle', 'htmlNodeRoot', 'browserDOM'], [1])
                add_question(quiz, 6, '¿Qué palabra clave declara una constante?', Question.Type.SINGLE, ['var', 'const', 'def', 'fixed'], [2])


        final_quiz, _ = Quiz.objects.get_or_create(
            course=course,
            module=None,
            kind=Quiz.Kind.FINAL,
            defaults={
                'title': 'Examen final · Desarrollo Web Profesional',
                'question_count': 10,
                'pass_percentage': 70,
                'max_attempts': 3,
                'randomize_questions': True,
                'randomize_choices': True,
                'is_required': True,
                'is_active': True,
            },
        )
        final_questions = [
            ('¿Qué etiqueta contiene metadatos y enlaces CSS?', Question.Type.SINGLE, ['<head>', '<main>', '<footer>', '<section>'], [1]),
            ('Selecciona técnicas responsive válidas.', Question.Type.MULTIPLE, ['media queries', 'max-width', 'grid/flex', 'tablas fijas de 1600px'], [1, 2, 3]),
            ('CSS Grid trabaja con filas y columnas.', Question.Type.SINGLE, ['Verdadero', 'Falso'], [1]),
            ('¿Qué evento se dispara al enviar un formulario?', Question.Type.SINGLE, ['submit', 'send', 'formend', 'postevent'], [1]),
            ('Selecciona afirmaciones correctas sobre Flexbox y Grid.', Question.Type.MULTIPLE, ['Flexbox funciona bien en un eje', 'Grid funciona bien en filas y columnas', 'Ambos pueden combinarse', 'Grid solo sirve para texto'], [1, 2, 3]),
            ('¿Qué propiedad evita que una imagen supere su contenedor?', Question.Type.SINGLE, ['max-width: 100%', 'width: 2000px', 'position: fixed', 'float: auto'], [1]),
            ('Selecciona etiquetas semánticas.', Question.Type.MULTIPLE, ['header', 'footer', 'article', 'blink'], [1, 2, 3]),
            ('JavaScript puede modificar clases CSS de un elemento.', Question.Type.SINGLE, ['Verdadero', 'Falso'], [1]),
            ('¿Qué API permite seleccionar elementos por CSS?', Question.Type.SINGLE, ['querySelector', 'cssFindServer', 'nodeSQL', 'templateSelect'], [1]),
            ('Selecciona criterios importantes antes de publicar una interfaz.', Question.Type.MULTIPLE, ['Responsive', 'Accesibilidad', 'Funcionamiento de interacciones', 'Ignorar errores visibles'], [1, 2, 3]),
            ('¿Qué atributo HTML ayuda a describir imágenes?', Question.Type.SINGLE, ['alt', 'href', 'rel', 'srcset-only'], [1]),
            ('Selecciona buenas prácticas de accesibilidad.', Question.Type.MULTIPLE, ['labels asociados', 'contraste legible', 'navegación por teclado', 'texto minúsculo ilegible'], [1, 2, 3]),
        ]
        for idx, (text, qtype, options, correct) in enumerate(final_questions, start=1):
            add_question(final_quiz, idx, text, qtype, options, correct)

        # Cursos visuales adicionales para probar tarjetas y portadas.
        extra_courses = [
            ('ia-aplicada-negocios-demo', 'IA Aplicada a Negocios', cat_ai, 'Automatización, análisis y uso práctico de inteligencia artificial.', 49, 'img/cursos-demo/curso-marketing.png'),
            ('marketing-digital-conversion-demo', 'Marketing Digital y Conversión', cat_marketing, 'Embudo, contenidos, automatización y métricas para campañas digitales.', 35, 'img/cursos-demo/curso-ecommerce.png'),
            ('desarrollo-software-proyecto-demo', 'Desarrollo de Software · Proyecto Final', cat_web, 'Curso visual de demostración para planificación, desarrollo y presentación de un proyecto de software.', 42, 'img/cursos-demo/curso-desarrollo-software.jpg'),
        ]
        for slug, title, category, desc, price, cover in extra_courses:
            extra, _ = Course.objects.get_or_create(
                slug=slug,
                defaults={
                    'title': title,
                    'short_description': desc,
                    'description': desc,
                    'category': category,
                    'price': price,
                    'created_by': admin,
                    'status': Course.Status.PUBLISHED,
                },
            )
            CourseInstructor.objects.get_or_create(course=extra, user=admin, defaults={'is_owner': True})
            attach_static_cover(extra, cover)
            if not extra.modules.exists():
                module = Module.objects.create(course=extra, order=1, title='Introducción', description='Módulo demostrativo', requires_quiz_to_unlock_next=False)
                Lesson.objects.create(module=module, order=1, title='Bienvenida al curso', description='Clase demostrativa', duration_minutes=8)

        BankAccount.objects.get_or_create(
            bank_name='Banco Pichincha',
            account_number='CONFIGURAR',
            defaults={'holder_name': 'Devlayer Academy', 'is_active': False},
        )
        self.stdout.write(self.style.SUCCESS('Datos demo listos: 4 cursos, uno completo con 3 módulos y evaluaciones.'))
