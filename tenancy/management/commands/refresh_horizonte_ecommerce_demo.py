from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from assessments.models import Quiz, QuizAttempt
from catalog.models import Course, Lesson
from catalog.pdf_tools import PDFMaterialError, optimize_pdf_bytes
from certificates.models import Certificate
from learning.models import Enrollment, LessonProgress
from tenancy.models import Academy
from tenancy.services import scope_courses


OLD_PDF_MARKER = 'Contenido extraído del material PDF:'


def _clean_old_extracted_text(description):
    return (description or '').split(OLD_PDF_MARKER, 1)[0].strip()


class Command(BaseCommand):
    help = 'Recarga y comprime los dos PDFs de E-commerce en Academia Horizonte y reinicia su progreso a 0%.'

    def _attach_optimized(self, field_file, relative_source, storage_name):
        source = Path(settings.BASE_DIR) / 'static' / relative_source
        if not source.exists():
            raise CommandError(f'No se encontró el PDF demo: {source}')
        try:
            optimized, info = optimize_pdf_bytes(source.read_bytes(), source.name)
        except PDFMaterialError as exc:
            raise CommandError(str(exc)) from exc
        storage = field_file.storage
        if storage.exists(storage_name):
            storage.delete(storage_name)
        field_file.name = storage.save(storage_name, ContentFile(optimized))
        return info

    @transaction.atomic
    def handle(self, *args, **options):
        academy = Academy.objects.filter(slug='academia-horizonte').first()
        if not academy:
            raise CommandError('No existe Academia Horizonte.')
        course = scope_courses(Course.objects.all(), academy).filter(slug='ecommerce-tienda-digital-horizonte').first()
        if not course:
            raise CommandError('No existe el curso demo de E-commerce. Ejecuta primero seed_horizonte_academic_demo.')

        lesson1 = Lesson.objects.filter(module__course=course, module__order=1, order=1).select_related('module').first()
        lesson2 = Lesson.objects.filter(module__course=course, module__order=2, order=1).select_related('module').first()
        if not lesson1 or not lesson2:
            raise CommandError('El curso no tiene la estructura demo esperada de dos módulos.')

        info1 = self._attach_optimized(
            lesson1.material_pdf,
            'demo/materials/ecommerce-modulo-1.pdf',
            'private/materials/demo/horizonte/ecommerce-modulo-1.pdf',
        )
        lesson1.description = _clean_old_extracted_text(lesson1.description)
        lesson1.save(update_fields=['material_pdf', 'description'])

        info2 = self._attach_optimized(
            lesson2.material_pdf,
            'demo/materials/ecommerce-modulo-2.pdf',
            'private/materials/demo/horizonte/ecommerce-modulo-2.pdf',
        )
        lesson2.description = _clean_old_extracted_text(lesson2.description)
        lesson2.save(update_fields=['material_pdf', 'description'])

        Quiz.objects.filter(course=course).update(show_correct_answers=True, max_attempts=3)
        course.masterclass_enabled = True
        course.masterclass_title = 'Clase magistral · E-commerce en acción'
        course.masterclass_description = (
            'Repaso final del curso, pautas prácticas para aplicar lo aprendido y espacio abierto '
            'para preguntas y resolución de dudas.'
        )
        if not course.masterclass_scheduled_at:
            course.masterclass_scheduled_at = timezone.now() + timedelta(days=7)
        course.masterclass_meeting_url = course.masterclass_meeting_url or 'https://meet.google.com/'
        course.masterclass_duration_minutes = 60
        course.save(update_fields=[
            'masterclass_enabled', 'masterclass_title', 'masterclass_description',
            'masterclass_scheduled_at', 'masterclass_meeting_url', 'masterclass_duration_minutes', 'updated_at',
        ])

        enrollment_ids = list(Enrollment.objects.filter(course=course).values_list('id', flat=True))
        if enrollment_ids:
            Certificate.objects.filter(enrollment_id__in=enrollment_ids).delete()
            QuizAttempt.objects.filter(enrollment_id__in=enrollment_ids).delete()
            LessonProgress.objects.filter(enrollment_id__in=enrollment_ids).delete()
            Enrollment.objects.filter(id__in=enrollment_ids).update(
                status=Enrollment.Status.ACTIVE,
                certified_at=None,
                blocked_reason='',
            )

        def kb(value):
            return f'{value / 1024:.1f} KB'

        self.stdout.write(self.style.SUCCESS('E-commerce Horizonte preparado para revisar desde cero.'))
        self.stdout.write(
            f'PDF Módulo 1: {info1["pages"]} pág. · {kb(info1["original_size"])} → {kb(info1["optimized_size"])} · PDF conservado'
        )
        self.stdout.write(
            f'PDF Módulo 2: {info2["pages"]} pág. · {kb(info2["original_size"])} → {kb(info2["optimized_size"])} · PDF conservado'
        )
        self.stdout.write(f'Matrículas reiniciadas: {len(enrollment_ids)}')
        self.stdout.write('Cuestionarios: mostrar respuestas = sí · intentos = 3 (editable por el profesor)')
        self.stdout.write('Clase magistral: habilitada')
        self.stdout.write('Materiales: visor horizontal por página; no se extrae texto ni se generan copias permanentes por página.')
