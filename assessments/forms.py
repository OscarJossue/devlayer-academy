from django import forms
from .models import Quiz


class QuizForm(forms.ModelForm):
    max_attempts = forms.TypedChoiceField(
        coerce=int,
        choices=[
            (0, 'Ilimitados'),
            (1, '1 intento'),
            (2, '2 intentos'),
            (3, '3 intentos'),
            (5, '5 intentos'),
        ],
        initial=3,
        label='Intentos permitidos',
    )

    class Meta:
        model = Quiz
        fields = [
            'title', 'kind', 'module', 'question_count', 'pass_percentage',
            'max_attempts', 'time_mode', 'time_limit_minutes', 'show_correct_answers', 'is_required',
        ]
        labels = {
            'title': 'Nombre de la evaluación',
            'kind': 'Tipo',
            'module': 'Módulo',
            'question_count': 'Preguntas por intento',
            'pass_percentage': 'Nota mínima (%)',
            'time_mode': 'Control de tiempo',
            'time_limit_minutes': 'Minutos',
            'show_correct_answers': 'Mostrar respuestas correctas al finalizar',
            'randomize_questions': 'Completar automáticamente con el banco de este módulo',
            'randomize_choices': 'Mezclar opciones de respuesta',
            'is_required': 'Obligatoria para avanzar',
        }
        help_texts = {
            'question_count': 'Academy selecciona esta cantidad desde el banco de preguntas.',
            'pass_percentage': 'Vacío = usa la nota mínima general del curso.',
            'show_correct_answers': 'Si se activa, después de enviar la evaluación el estudiante verá qué marcó y cuál era la respuesta correcta.',
            'time_mode': 'Sin tiempo, límite estricto o cronómetro recomendado.',
            'time_limit_minutes': 'Se usa en Tiempo límite y Cronómetro recomendado.',
        }
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': 'Ej. Cuestionario del módulo 1'}),
            'question_count': forms.NumberInput(attrs={'min': 1, 'placeholder': '10'}),
            'pass_percentage': forms.NumberInput(attrs={'min': 1, 'max': 100, 'placeholder': '70'}),
            'time_limit_minutes': forms.NumberInput(attrs={'min': 1, 'max': 600, 'placeholder': 'Ej. 20'}),
        }

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get('time_mode')
        minutes = cleaned.get('time_limit_minutes')
        if mode != Quiz.TimeMode.NONE and not minutes:
            self.add_error('time_limit_minutes', 'Indica los minutos para esta modalidad de tiempo.')
        if mode == Quiz.TimeMode.NONE:
            cleaned['time_limit_minutes'] = None
            self.instance.time_limit_minutes = None
        return cleaned


class QuizSettingsForm(forms.ModelForm):
    max_attempts = forms.TypedChoiceField(
        coerce=int,
        choices=[
            (0, 'Ilimitados'),
            (1, '1 intento'),
            (2, '2 intentos'),
            (3, '3 intentos'),
            (5, '5 intentos'),
        ],
        label='Intentos permitidos',
    )

    class Meta:
        model = Quiz
        fields = [
            'title', 'question_count', 'pass_percentage', 'max_attempts', 'time_mode', 'time_limit_minutes',
            'show_correct_answers', 'randomize_questions', 'randomize_choices', 'is_required',
        ]
        labels = {
            'title': 'Nombre de la evaluación',
            'question_count': 'Preguntas por intento',
            'pass_percentage': 'Nota mínima (%)',
            'time_mode': 'Control de tiempo',
            'time_limit_minutes': 'Minutos',
            'show_correct_answers': 'Mostrar respuestas correctas al finalizar',
            'randomize_questions': 'Completar automáticamente con el banco de este módulo',
            'randomize_choices': 'Mezclar opciones de respuesta',
            'is_required': 'Obligatoria para avanzar',
        }
        help_texts = {
            'question_count': 'Cantidad de preguntas que tendrá cada intento.',
            'pass_percentage': 'Vacío = usa la nota mínima general del curso.',
            'time_mode': 'Tiempo límite cierra el intento al llegar a cero. Cronómetro recomendado permite continuar y registra el exceso.',
            'time_limit_minutes': 'Objetivo o límite del intento, entre 1 y 600 minutos.',
            'randomize_questions': 'Prioriza el XLSX más reciente y, si faltan preguntas, completa al azar solo con el banco anterior de este mismo módulo.',
        }
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': 'Nombre de la evaluación'}),
            'question_count': forms.NumberInput(attrs={'min': 1}),
            'pass_percentage': forms.NumberInput(attrs={'min': 1, 'max': 100}),
            'time_limit_minutes': forms.NumberInput(attrs={'min': 1, 'max': 600, 'placeholder': 'Ej. 20'}),
        }

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get('time_mode')
        minutes = cleaned.get('time_limit_minutes')
        if mode != Quiz.TimeMode.NONE and not minutes:
            self.add_error('time_limit_minutes', 'Indica los minutos para esta modalidad de tiempo.')
        if mode == Quiz.TimeMode.NONE:
            cleaned['time_limit_minutes'] = None
            self.instance.time_limit_minutes = None
        return cleaned


class QuestionImportForm(forms.Form):
    file = forms.FileField(
        label='Archivo XLSX de preguntas',
        help_text='El archivo se procesa para mostrar una vista previa y no se almacena en la plataforma.',
        widget=forms.ClearableFileInput(attrs={'accept': '.xlsx'}),
    )
