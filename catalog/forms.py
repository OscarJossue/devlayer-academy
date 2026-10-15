from django import forms
from .models import Course, Module, Lesson


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = [
            'title', 'short_description', 'description', 'category', 'thumbnail',
            'price', 'currency', 'sequential_learning', 'default_pass_percentage',
            'access_type', 'access_days', 'access_fixed_until',
            'post_certificate_policy', 'post_certificate_days', 'final_exam_required',
        ]
        labels = {
            'title': 'Nombre del curso',
            'short_description': 'Descripción corta',
            'description': 'Descripción completa',
            'category': 'Categoría',
            'thumbnail': 'Portada del curso',
            'price': 'Precio',
            'currency': 'Moneda',
            'sequential_learning': 'Aprendizaje secuencial',
            'default_pass_percentage': 'Nota mínima predeterminada (%)',
            'access_type': 'Tipo de acceso',
            'access_days': 'Días de acceso',
            'access_fixed_until': 'Fecha límite de acceso',
            'post_certificate_policy': 'Acceso después de certificar',
            'post_certificate_days': 'Días adicionales después de certificar',
            'final_exam_required': 'Examen final obligatorio',
        }
        help_texts = {
            'title': 'Usa un nombre claro y corto. Ejemplo: Python desde cero.',
            'short_description': 'Máximo 280 caracteres. Se muestra en la tarjeta del catálogo.',
            'thumbnail': 'Imagen horizontal recomendada: 1600 × 900 px.',
            'price': 'Usa 0 para un curso gratuito.',
            'default_pass_percentage': 'Se usa cuando una evaluación no define su propia nota mínima.',
            'sequential_learning': 'Si está activo, el estudiante debe avanzar en el orden definido.',
        }
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': 'Ej. Python desde cero'}),
            'short_description': forms.TextInput(attrs={'placeholder': 'Resume en una frase qué aprenderá el estudiante'}),
            'description': forms.Textarea(attrs={'placeholder': 'Explica objetivos, contenido, requisitos y resultados esperados', 'rows': 5}),
            'price': forms.NumberInput(attrs={'placeholder': '0.00', 'step': '0.01'}),
            'currency': forms.TextInput(attrs={'placeholder': 'USD'}),
            'access_days': forms.NumberInput(attrs={'placeholder': 'Ej. 90'}),
            'access_fixed_until': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'post_certificate_days': forms.NumberInput(attrs={'placeholder': 'Ej. 30'}),
        }


class ModuleForm(forms.ModelForm):
    class Meta:
        model = Module
        fields = ['title', 'description', 'order', 'requires_quiz_to_unlock_next']
        labels = {
            'title': 'Nombre del módulo',
            'description': 'Descripción',
            'order': 'Orden',
            'requires_quiz_to_unlock_next': 'Exigir cuestionario para desbloquear el siguiente módulo',
        }
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': 'Ej. Fundamentos de Python'}),
            'description': forms.Textarea(attrs={'placeholder': 'Describe brevemente qué cubre este módulo', 'rows': 4}),
            'order': forms.NumberInput(attrs={'min': 1, 'placeholder': '1'}),
        }


class LessonForm(forms.ModelForm):
    class Meta:
        model = Lesson
        fields = ['title', 'description', 'order', 'duration_minutes', 'video_provider', 'video_source', 'material_pdf', 'is_preview']
        labels = {
            'title': 'Nombre de la clase',
            'description': 'Contenido o descripción de la clase',
            'order': 'Orden',
            'duration_minutes': 'Duración aproximada (minutos)',
            'video_provider': 'Tipo de video',
            'video_source': 'URL o ID del video',
            'material_pdf': 'Material PDF',
            'is_preview': 'Permitir vista previa',
        }
        help_texts = {
            'video_source': 'Pega la URL del video de YouTube no listado o su ID. El valor se guarda cifrado en la base de datos.',
            'material_pdf': 'PDF opcional. Se sirve mediante una URL temporal protegida.',
            'is_preview': 'Actívalo solo si esta clase puede verse antes de comprar el curso.',
        }
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': 'Ej. Variables, tipos de datos y operadores'}),
            'description': forms.Textarea(attrs={'placeholder': 'Añade una explicación breve, objetivos o instrucciones para la clase', 'rows': 5}),
            'order': forms.NumberInput(attrs={'min': 1, 'placeholder': '1'}),
            'duration_minutes': forms.NumberInput(attrs={'min': 0, 'placeholder': '15'}),
            'video_source': forms.TextInput(attrs={'placeholder': 'https://youtu.be/ID_DEL_VIDEO o ID_DEL_VIDEO'}),
        }




class CourseContentImportForm(forms.Form):
    xlsx_file = forms.FileField(
        label='Archivo XLSX de contenido',
        help_text='El XLSX solo se lee para importar texto y referencias; el archivo XLSX no se almacena en la plataforma.',
        widget=forms.ClearableFileInput(attrs={'accept': '.xlsx'}),
    )
