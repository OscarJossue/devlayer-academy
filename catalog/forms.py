from django import forms
from tenancy.services import scope_categories
from .models import Category, Course, Module, Lesson
from .pdf_tools import PDFMaterialError, optimize_pdf_upload


class CourseForm(forms.ModelForm):
    def __init__(self, *args, academy=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = scope_categories(Category.objects.filter(is_active=True), academy) if academy else Category.objects.none()
        # En cursos nuevos la certificación debe ser una decisión explícita del profesor.
        if not getattr(self.instance, 'pk', None) and not self.is_bound:
            self.fields['certificate_enabled'].initial = False
            self.fields['certificate_style_mode'].initial = Course.CertificateStyleMode.ACADEMY

    def clean(self):
        cleaned = super().clean()
        certificate_enabled = (
            cleaned.get('certificate_enabled')
            if 'certificate_enabled' in self.fields
            else getattr(self.instance, 'certificate_enabled', False)
        )
        if not certificate_enabled and cleaned.get('access_type') == Course.AccessType.UNTIL_CERTIFICATE:
            self.add_error('access_type', 'El acceso “Hasta certificarse” requiere que el curso otorgue certificado.')
        return cleaned

    class Meta:
        model = Course
        fields = [
            'title', 'short_description', 'description', 'category', 'thumbnail',
            'price', 'currency', 'sequential_learning', 'default_pass_percentage',
            'access_type', 'access_days', 'access_fixed_until',
            'post_certificate_policy', 'post_certificate_days', 'final_exam_required',
            'certificate_enabled', 'certificate_style_mode',
        ]
        labels = {
            'title': 'Nombre del curso', 'short_description': 'Descripción corta', 'description': 'Descripción completa',
            'category': 'Categoría', 'thumbnail': 'Portada del curso', 'price': 'Precio', 'currency': 'Moneda',
            'sequential_learning': 'Aprendizaje secuencial', 'default_pass_percentage': 'Nota mínima predeterminada (%)',
            'access_type': 'Tipo de acceso', 'access_days': 'Días de acceso', 'access_fixed_until': 'Fecha límite de acceso',
            'post_certificate_policy': 'Acceso después de certificar', 'post_certificate_days': 'Días adicionales después de certificar',
            'final_exam_required': 'Examen final obligatorio',
            'certificate_enabled': 'Este curso otorga certificado',
            'certificate_style_mode': 'Diseño del certificado',
        }
        help_texts = {
            'title': 'Usa un nombre claro y corto. Ejemplo: Python desde cero.',
            'short_description': 'Máximo 280 caracteres. Se muestra en la tarjeta del catálogo.',
            'thumbnail': 'Imagen horizontal recomendada: 1600 × 900 px.', 'price': 'Usa 0 para un curso gratuito.',
            'default_pass_percentage': 'Se usa cuando una evaluación no define su propia nota mínima.',
            'sequential_learning': 'Si está activo, el estudiante debe avanzar en el orden definido.',
            'certificate_enabled': 'Si está desactivado, el curso termina sin generar certificado.',
            'certificate_style_mode': 'Puedes usar el diseño general definido por el dueño o crear uno propio para este curso.',
        }
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': 'Ej. Python desde cero'}),
            'short_description': forms.TextInput(attrs={'placeholder': 'Resume en una frase qué aprenderá el estudiante'}),
            'description': forms.Textarea(attrs={'placeholder': 'Explica objetivos, contenido, requisitos y resultados esperados', 'rows': 5}),
            'price': forms.NumberInput(attrs={'placeholder': '0.00', 'step': '0.01'}), 'currency': forms.TextInput(attrs={'placeholder': 'USD'}),
            'access_days': forms.NumberInput(attrs={'placeholder': 'Ej. 90'}), 'access_fixed_until': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'post_certificate_days': forms.NumberInput(attrs={'placeholder': 'Ej. 30'}),
        }


class ModuleForm(forms.ModelForm):
    """Carga rápida de módulos: el orden se calcula automáticamente en la vista."""
    class Meta:
        model = Module
        fields = ['title', 'description', 'requires_quiz_to_unlock_next']
        labels = {
            'title': 'Nombre del módulo',
            'description': 'Resumen breve',
            'requires_quiz_to_unlock_next': 'Exigir cuestionario aprobado para avanzar',
        }
        help_texts = {
            'requires_quiz_to_unlock_next': 'Recomendado. El estudiante puede volver a revisar las clases anteriores en cualquier momento.',
        }
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': 'Ej. Fundamentos del e-commerce'}),
            'description': forms.Textarea(attrs={'placeholder': 'Qué aprenderá el estudiante en este módulo', 'rows': 3}),
        }


class LessonForm(forms.ModelForm):
    """Carga rápida: el PDF se conserva como PDF y se optimiza automáticamente."""

    def clean_material_pdf(self):
        upload = self.cleaned_data.get('material_pdf')
        if not upload:
            return upload
        try:
            optimized, info = optimize_pdf_upload(upload)
        except PDFMaterialError as exc:
            raise forms.ValidationError(str(exc)) from exc
        self.pdf_optimization_info = info
        return optimized

    class Meta:
        model = Lesson
        fields = ['title', 'video_source', 'material_pdf', 'duration_minutes', 'description']
        labels = {
            'title': 'Nombre de la clase',
            'video_source': 'Video de YouTube',
            'material_pdf': 'PDF de apoyo',
            'duration_minutes': 'Duración aproximada',
            'description': 'Resumen / indicaciones',
        }
        help_texts = {
            'video_source': 'Pega la URL o el ID de YouTube. Si lo dejas vacío, la clase puede ser solo material.',
            'material_pdf': 'Sube el PDF original. Academy lo comprime automáticamente conservando páginas, diseño, imágenes y texto. No se convierte a texto y el alumno no recibe una descarga directa.',
            'duration_minutes': 'Puedes dejar el valor sugerido y cambiarlo solo si lo necesitas.',
        }
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': 'Ej. Diseña una tienda que el cliente entienda'}),
            'video_source': forms.TextInput(attrs={'placeholder': 'https://www.youtube.com/watch?v=...'}),
            'material_pdf': forms.ClearableFileInput(attrs={'accept': '.pdf,application/pdf'}),
            'duration_minutes': forms.NumberInput(attrs={'min': 0, 'placeholder': '15'}),
            'description': forms.Textarea(attrs={'placeholder': 'Opcional: objetivos o indicaciones rápidas', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound and not getattr(self.instance, 'pk', None):
            self.fields['duration_minutes'].initial = 15


class CourseMasterclassForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = [
            'masterclass_enabled', 'masterclass_title', 'masterclass_scheduled_at',
            'masterclass_duration_minutes', 'masterclass_meeting_url', 'masterclass_description',
        ]
        labels = {
            'masterclass_enabled': 'Habilitar clase magistral',
            'masterclass_title': 'Título',
            'masterclass_scheduled_at': 'Fecha y hora',
            'masterclass_duration_minutes': 'Duración aproximada (min)',
            'masterclass_meeting_url': 'Link de videoconferencia',
            'masterclass_description': 'Indicaciones para los estudiantes',
        }
        help_texts = {
            'masterclass_enabled': 'Si la desactivas, este apartado desaparece para los estudiantes sin borrar la configuración.',
            'masterclass_meeting_url': 'Google Meet, Zoom, Teams u otra plataforma.',
        }
        widgets = {
            'masterclass_scheduled_at': forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}),
            'masterclass_duration_minutes': forms.NumberInput(attrs={'min': 10, 'step': 5}),
            'masterclass_meeting_url': forms.URLInput(attrs={'placeholder': 'https://meet.google.com/...'}),
            'masterclass_description': forms.Textarea(attrs={
                'rows': 4,
                'placeholder': 'Resumen del curso, indicaciones, pautas y espacio para resolver dudas y preguntas.',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['masterclass_scheduled_at'].input_formats = ['%Y-%m-%dT%H:%M']
        if not self.is_bound and not getattr(self.instance, 'masterclass_description', ''):
            self.initial['masterclass_description'] = (
                'En esta clase magistral repasaremos los puntos principales del curso, daremos pautas finales '
                'y resolveremos preguntas y dudas de los estudiantes.'
            )


class CourseContentImportForm(forms.Form):
    xlsx_file = forms.FileField(label='Archivo XLSX de contenido', help_text='El XLSX se lee para importar datos y luego se descarta.', widget=forms.ClearableFileInput(attrs={'accept': '.xlsx'}))


class CourseCertificateStyleForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = [
            'certificate_enabled', 'certificate_style_mode',
            'certificate_custom_title', 'certificate_custom_subtitle', 'certificate_custom_body',
            'certificate_custom_accent_color', 'certificate_custom_background_color', 'certificate_custom_text_color',
            'certificate_custom_signature_name', 'certificate_custom_signature_role', 'certificate_custom_signature_image',
            'certificate_custom_footer', 'certificate_custom_show_logo', 'certificate_custom_show_qr',
        ]
        labels = {
            'certificate_enabled': 'Este curso otorga certificado',
            'certificate_style_mode': 'Diseño a utilizar',
            'certificate_custom_title': 'Título principal',
            'certificate_custom_subtitle': 'Texto antes del estudiante',
            'certificate_custom_body': 'Texto antes del curso',
            'certificate_custom_accent_color': 'Color de acento',
            'certificate_custom_background_color': 'Color de fondo',
            'certificate_custom_text_color': 'Color del texto',
            'certificate_custom_signature_name': 'Nombre de quien firma',
            'certificate_custom_signature_role': 'Cargo de quien firma',
            'certificate_custom_signature_image': 'Firma (imagen opcional)',
            'certificate_custom_footer': 'Texto inferior',
            'certificate_custom_show_logo': 'Mostrar logo de la academia',
            'certificate_custom_show_qr': 'Mostrar QR de validación',
        }
        widgets = {
            'certificate_custom_title': forms.TextInput(attrs={'placeholder': 'Vacío = usar valor de la academia'}),
            'certificate_custom_subtitle': forms.TextInput(attrs={'placeholder': 'Vacío = usar valor de la academia'}),
            'certificate_custom_body': forms.TextInput(attrs={'placeholder': 'Vacío = usar valor de la academia'}),
            'certificate_custom_accent_color': forms.TextInput(attrs={'type': 'color'}),
            'certificate_custom_background_color': forms.TextInput(attrs={'type': 'color'}),
            'certificate_custom_text_color': forms.TextInput(attrs={'type': 'color'}),
            'certificate_custom_signature_name': forms.TextInput(attrs={'placeholder': 'Vacío = usar firma de la academia'}),
            'certificate_custom_signature_role': forms.TextInput(attrs={'placeholder': 'Vacío = usar cargo de la academia'}),
            'certificate_custom_signature_image': forms.FileInput(attrs={'accept': 'image/png,image/jpeg,image/webp'}),
            'certificate_custom_footer': forms.TextInput(attrs={'placeholder': 'Vacío = usar texto de la academia'}),
        }

    def __init__(self, *args, academy=None, **kwargs):
        self.academy = academy
        super().__init__(*args, **kwargs)
        if self.instance:
            defaults = {
                'certificate_custom_accent_color': getattr(academy, 'certificate_accent_color', '') or getattr(academy, 'brand_color', '#1458D6'),
                'certificate_custom_background_color': getattr(academy, 'certificate_background_color', '#FFFFFF'),
                'certificate_custom_text_color': getattr(academy, 'certificate_text_color', '#172033'),
            }
            for field, value in defaults.items():
                if not getattr(self.instance, field, ''):
                    self.initial[field] = value

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('certificate_enabled'):
            return cleaned
        if cleaned.get('certificate_style_mode') == Course.CertificateStyleMode.CUSTOM:
            for field in ('certificate_custom_accent_color', 'certificate_custom_background_color', 'certificate_custom_text_color'):
                value = cleaned.get(field)
                if value and (len(value) != 7 or not value.startswith('#')):
                    self.add_error(field, 'Selecciona un color válido.')
        return cleaned
