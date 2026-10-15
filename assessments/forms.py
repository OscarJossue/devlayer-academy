from django import forms
from .models import Quiz


class QuizForm(forms.ModelForm):
    class Meta:
        model = Quiz
        fields = ['title', 'kind', 'module', 'question_count', 'pass_percentage', 'max_attempts', 'randomize_questions', 'randomize_choices', 'is_required']
        labels = {
            'title': 'Nombre de la evaluación',
            'kind': 'Tipo de evaluación',
            'module': 'Módulo',
            'question_count': 'Preguntas por intento',
            'pass_percentage': 'Nota mínima (%)',
            'max_attempts': 'Número máximo de intentos',
            'randomize_questions': 'Elegir preguntas al azar',
            'randomize_choices': 'Mezclar respuestas',
            'is_required': 'Evaluación obligatoria',
        }
        help_texts = {
            'question_count': 'El sistema seleccionará esta cantidad desde el banco de preguntas.',
            'pass_percentage': 'Déjalo vacío para usar la nota mínima general del curso.',
            'max_attempts': 'Usa 0 para intentos ilimitados.',
        }
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': 'Ej. Cuestionario del módulo 1'}),
            'question_count': forms.NumberInput(attrs={'min': 1, 'placeholder': '10'}),
            'pass_percentage': forms.NumberInput(attrs={'min': 1, 'max': 100, 'placeholder': '70'}),
            'max_attempts': forms.NumberInput(attrs={'min': 0, 'placeholder': '3'}),
        }


class QuestionImportForm(forms.Form):
    file = forms.FileField(
        label='Archivo XLSX de preguntas',
        help_text='El archivo se procesa para mostrar una vista previa y no se almacena en la plataforma.',
        widget=forms.ClearableFileInput(attrs={'accept': '.xlsx'}),
    )
