from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from assessments.models import QuizAttempt
from catalog.models import Course
from certificates.models import Certificate
from learning.models import Enrollment, LessonProgress
from tenancy.models import Academy
from tenancy.services import scope_courses


class Command(BaseCommand):
    help = (
        'Reinicia el progreso académico de uno o varios estudiantes sin eliminar '
        'la matrícula, el pago ni el acceso al curso.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--academy', required=True, help='Slug de la academia.')
        parser.add_argument('--course', help='Slug del curso. Requerido salvo --all-courses.')
        parser.add_argument('--email', help='Correo del estudiante que se reiniciará.')
        parser.add_argument(
            '--all-students',
            action='store_true',
            help='Reinicia a todos los estudiantes matriculados en el curso seleccionado.',
        )
        parser.add_argument(
            '--all-courses',
            action='store_true',
            help='Aplica el reinicio a todos los cursos de la academia.',
        )
        parser.add_argument(
            '--yes',
            action='store_true',
            help='Confirma la operación sin pedir confirmación interactiva.',
        )

    def handle(self, *args, **options):
        academy_slug = options['academy'].strip()
        course_slug = (options.get('course') or '').strip()
        email = (options.get('email') or '').strip().lower()
        all_students = options['all_students']
        all_courses = options['all_courses']

        if not all_students and not email:
            raise CommandError('Indica --email correo@dominio.com o usa --all-students.')
        if all_students and email:
            raise CommandError('Usa --email o --all-students, no ambos a la vez.')
        if not all_courses and not course_slug:
            raise CommandError('Indica --course <slug> o usa --all-courses.')
        if all_courses and course_slug:
            raise CommandError('Usa --course o --all-courses, no ambos a la vez.')

        try:
            academy = Academy.objects.get(slug=academy_slug)
        except Academy.DoesNotExist as exc:
            raise CommandError(f'No existe una academia con slug "{academy_slug}".') from exc

        courses = scope_courses(Course.objects.all(), academy)
        if not all_courses:
            courses = courses.filter(slug=course_slug)
            if not courses.exists():
                raise CommandError(
                    f'No existe el curso "{course_slug}" dentro de {academy.name}.'
                )

        enrollments = Enrollment.objects.filter(course__in=courses).select_related('course', 'user')
        if email:
            enrollments = enrollments.filter(user__email__iexact=email)

        enrollment_ids = list(enrollments.values_list('id', flat=True))
        if not enrollment_ids:
            target = email or 'los estudiantes seleccionados'
            raise CommandError(f'No se encontraron matrículas para {target}.')

        course_names = list(courses.values_list('title', flat=True))
        self.stdout.write(self.style.WARNING('Se reiniciará únicamente el progreso académico.'))
        self.stdout.write(f'Academia: {academy.name} ({academy.slug})')
        self.stdout.write(f'Cursos: {", ".join(course_names)}')
        self.stdout.write(f'Matrículas afectadas: {len(enrollment_ids)}')
        self.stdout.write('Se conservarán: usuario, membresía, matrícula, pago y acceso al curso.')
        self.stdout.write('Se eliminarán: progreso de clases, intentos/respuestas y certificado emitido.')

        if not options['yes']:
            confirmation = input('Escribe RESET para continuar: ').strip()
            if confirmation != 'RESET':
                self.stdout.write(self.style.WARNING('Operación cancelada.'))
                return

        with transaction.atomic():
            certificates = Certificate.objects.filter(enrollment_id__in=enrollment_ids)
            certificate_count = certificates.count()
            certificates.delete()

            attempts = QuizAttempt.objects.filter(enrollment_id__in=enrollment_ids)
            attempt_count = attempts.count()
            attempts.delete()

            lesson_progress = LessonProgress.objects.filter(enrollment_id__in=enrollment_ids)
            lesson_progress_count = lesson_progress.count()
            lesson_progress.delete()

            updated = Enrollment.objects.filter(id__in=enrollment_ids).update(
                status=Enrollment.Status.ACTIVE,
                certified_at=None,
                blocked_reason='',
            )

        self.stdout.write(self.style.SUCCESS('Progreso reiniciado correctamente.'))
        self.stdout.write(f'Progresos de clase eliminados: {lesson_progress_count}')
        self.stdout.write(f'Intentos de evaluación eliminados: {attempt_count}')
        self.stdout.write(f'Certificados eliminados: {certificate_count}')
        self.stdout.write(f'Matrículas devueltas a ACTIVO: {updated}')
        self.stdout.write(self.style.SUCCESS('El estudiante vuelve a iniciar el curso desde 0%.'))
