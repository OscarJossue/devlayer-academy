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
            'max_attempts', 'show_correct_answers', 'is_required',
        ]
        labels = {
            'title': 'Nombre de la evaluación',
            'kind': 'Tipo',
            'module': 'Módulo',
            'question_count': 'Preguntas por intento',
            'pass_percentage': 'Nota mínima (%)',
            'show_correct_answers': 'Mostrar respuestas correctas al finalizar',
            'is_required': 'Obligatoria para avanzar',
        }
        help_texts = {
            'question_count': 'Academy selecciona esta cantidad desde el banco de preguntas.',
            'pass_percentage': 'Vacío = usa la nota mínima general del curso.',
            'show_correct_answers': 'Si se activa, después de enviar la evaluación el estudiante verá qué marcó y cuál era la respuesta correcta.',
        }
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': 'Ej. Cuestionario del módulo 1'}),
            'question_count': forms.NumberInput(attrs={'min': 1, 'placeholder': '10'}),
            'pass_percentage': forms.NumberInput(attrs={'min': 1, 'max': 100, 'placeholder': '70'}),
        }


class QuestionImportForm(forms.Form):
    file = forms.FileField(
        label='Archivo XLSX de preguntas',
        help_text='El archivo se procesa para mostrar una vista previa y no se almacena en la plataforma.',
        widget=forms.ClearableFileInput(attrs={'accept': '.xlsx'}),
    )
