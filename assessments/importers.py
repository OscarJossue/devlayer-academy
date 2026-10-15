from openpyxl import load_workbook
from django.db import transaction
from .models import Choice, Question

HEADERS = [
    'pregunta', 'tipo', 'opcion_a', 'opcion_b', 'opcion_c', 'opcion_d',
    'respuesta_correcta', 'explicacion',
]

OPEN_TYPE = 'OPEN'
TYPE_MAP = {
    'unica': Question.Type.SINGLE,
    'única': Question.Type.SINGLE,
    'opcion_unica': Question.Type.SINGLE,
    'opción_única': Question.Type.SINGLE,
    'single': Question.Type.SINGLE,
    'multiple': Question.Type.MULTIPLE,
    'múltiple': Question.Type.MULTIPLE,
    'seleccion_multiple': Question.Type.MULTIPLE,
    'selección_múltiple': Question.Type.MULTIPLE,
    'verdadero_falso': Question.Type.TRUE_FALSE,
    'true_false': Question.Type.TRUE_FALSE,
    'abierta': OPEN_TYPE,
    'pregunta_abierta': OPEN_TYPE,
    'open': OPEN_TYPE,
}


def question_type_label(value):
    if value == OPEN_TYPE:
        return 'Pregunta abierta'
    return dict(Question.Type.choices).get(value, value)


def read_question_xlsx(upload):
    if not upload.name.lower().endswith('.xlsx'):
        raise ValueError('Usa un archivo XLSX de preguntas.')
    wb = load_workbook(upload, read_only=True, data_only=True)
    ws = wb.active
    values = ws.iter_rows(values_only=True)
    try:
        headers = [str(x or '').strip().lower() for x in next(values)]
    except StopIteration:
        return [], ['El archivo XLSX está vacío.']
    missing = [h for h in HEADERS if h not in headers]
    if missing:
        raise ValueError('Faltan columnas obligatorias: ' + ', '.join(missing))
    rows = []
    errors = []
    for index, values_row in enumerate(values, start=2):
        raw = dict(zip(headers, values_row))
        if not any(v not in (None, '') for v in values_row):
            continue
        text = str(raw.get('pregunta') or '').strip()
        qtype = TYPE_MAP.get(str(raw.get('tipo') or 'unica').strip().lower())
        if not text:
            errors.append(f'Fila {index}: falta la pregunta.')
            continue
        if not qtype:
            errors.append(f'Fila {index}: tipo de pregunta no reconocido.')
            continue
        row = {
            'fila': index,
            'pregunta': text,
            'tipo': qtype,
            'tipo_label': question_type_label(qtype),
            'opcion_a': str(raw.get('opcion_a') or '').strip(),
            'opcion_b': str(raw.get('opcion_b') or '').strip(),
            'opcion_c': str(raw.get('opcion_c') or '').strip(),
            'opcion_d': str(raw.get('opcion_d') or '').strip(),
            'respuesta_correcta': str(raw.get('respuesta_correcta') or '').upper().replace(' ', ''),
            'explicacion': str(raw.get('explicacion') or '').strip(),
        }
        if qtype != OPEN_TYPE:
            options = [row['opcion_a'], row['opcion_b'], row['opcion_c'], row['opcion_d']]
            if qtype == Question.Type.TRUE_FALSE and not any(options):
                row['opcion_a'], row['opcion_b'] = 'Verdadero', 'Falso'
                if not row['respuesta_correcta']:
                    row['respuesta_correcta'] = 'A'
            if not any([row['opcion_a'], row['opcion_b'], row['opcion_c'], row['opcion_d']]):
                errors.append(f'Fila {index}: una pregunta cerrada debe tener opciones.')
            if not row['respuesta_correcta']:
                errors.append(f'Fila {index}: falta respuesta_correcta.')
        rows.append(row)
    return rows, errors


@transaction.atomic
def import_question_rows(quiz, rows):
    created = 0
    errors = []
    next_order = quiz.questions.count() + 1
    valid_types = {x[0] for x in Question.Type.choices} | {OPEN_TYPE}
    for row in rows:
        qtype = row.get('tipo')
        text = str(row.get('pregunta') or '').strip()
        if not text or qtype not in valid_types:
            errors.append(f"Fila {row.get('fila', '?')}: pregunta inválida.")
            continue
        question = Question.objects.create(
            quiz=quiz,
            text=text,
            question_type=qtype,
            explanation=str(row.get('explicacion') or '').strip(),
            order=next_order,
        )
        next_order += 1
        if qtype != OPEN_TYPE:
            correct_raw = str(row.get('respuesta_correcta') or '').upper().replace(' ', '')
            correct = {x for x in correct_raw.replace(';', ',').split(',') if x}
            for pos, letter in enumerate(['A', 'B', 'C', 'D'], start=1):
                value = str(row.get(f'opcion_{letter.lower()}') or '').strip()
                if value:
                    Choice.objects.create(question=question, text=value, is_correct=letter in correct, order=pos)
            if not question.choices.filter(is_correct=True).exists():
                question.delete()
                errors.append(f"Fila {row.get('fila', '?')}: pregunta omitida porque no tiene respuesta correcta.")
                continue
        created += 1
    return created, errors


@transaction.atomic
def reuse_questions(target_quiz, source_questions):
    copied = 0
    order = target_quiz.questions.count() + 1
    for source in source_questions.prefetch_related('choices'):
        question = Question.objects.create(
            quiz=target_quiz,
            text=source.text,
            question_type=source.question_type,
            explanation=source.explanation,
            is_active=True,
            order=order,
        )
        order += 1
        for choice in source.choices.all():
            # No copiamos respuestas temporales creadas por estudiantes en preguntas abiertas.
            if source.question_type == OPEN_TYPE and choice.text.startswith('__RESPUESTA__'):
                continue
            Choice.objects.create(
                question=question,
                text=choice.text,
                is_correct=choice.is_correct,
                order=choice.order,
            )
        copied += 1
    return copied
