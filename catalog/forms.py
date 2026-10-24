from django import forms
from tenancy.services import scope_categories
from .models import Category, Course, Module, Lesson
from .pdf_tools import PDFMaterialError, optimize_pdf_upload


class CourseForm(forms.ModelForm):
    def __init__(self, *args, academy=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = (
            scope_categories(Category.objects.filter(is_active=True), academy)
            if academy else Category.objects.none()
        )

    def clean(self):
        cleaned = super().clean()
        certificate_enabled = (getattr(self.instance, 'certificate_enabled', False) if getattr(self.instance, 'pk', None) else False)
        if not certificate_enabled and cleaned.get('access_type') == Course.AccessType.UNTIL_CERTIFICATE:
            self.add_error(
                'access_type',
                'El acceso “Hasta certificarse” requiere habilitar primero el certificado en el apartado Certificación.',
            )
        return cleaned

    class Meta:
        model = Course
        fields = [
            'title', 'short_description', 'description', 'category', 'thumbnail',
            'price', 'currency', 'sequential_learning', 'default_pass_percentage',
            'access_type', 'access_days', 'access_fixed_until',
            'post_certificate_policy', 'post_certificate_days', 'final_exam_required',
        ]
        labels = {
            'title': 'Nombre del curso', 'short_description': 'Descripción corta', 'description': 'Descripción completa',
            'category': 'Categoría', 'thumbnail': 'Portada del curso', 'price': 'Precio', 'currency': 'Moneda',
            'sequential_learning': 'Aprendizaje secuencial', 'default_pass_percentage': 'Nota mínima predeterminada (%)',
            'access_type': 'Tipo de acceso', 'access_days': 'Días de acceso', 'access_fixed_until': 'Fecha límite de acceso',
            'post_certificate_policy': 'Acceso después de certificar', 'post_certificate_days': 'Días adicionales después de certificar',
            'final_exam_required': 'Examen final obligatorio',
        }
        help_texts = {
            'title': 'Usa un nombre claro y corto. Ejemplo: Python desde cero.',
            'short_description': 'Máximo 280 caracteres. Se muestra en la tarjeta del catálogo.',
            'thumbnail': 'Imagen horizontal recomendada: 1600 × 900 px.', 'price': 'Usa 0 para un curso gratuito.',
            'default_pass_percentage': 'Se usa cuando una evaluación no define su propia nota mínima.',
            'sequential_learning': 'Si está activo, el estudiante debe avanzar en el orden definido.',
            'final_exam_required': 'La configuración detallada del examen se realiza únicamente en “Examen final”.',
        }
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': 'Ej. Python desde cero'}),
            'short_description': forms.TextInput(attrs={'placeholder': 'Resume en una frase qué aprenderá el estudiante'}),
            'description': forms.Textarea(attrs={'placeholder': 'Explica objetivos, contenido, requisitos y resultados esperados', 'rows': 5}),
            'price': forms.NumberInput(attrs={'placeholder': '0.00', 'step': '0.01'}), 'currency': forms.TextInput(attrs={'placeholder': 'USD'}),
            'access_days': forms.NumberInput(attrs={'placeholder': 'Ej. 90'}), 'access_fixed_until': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'post_certificate_days': forms.NumberInput(attrs={'placeholder': 'Ej. 30'}),
        }


class ProfessorCategoryForm(forms.ModelForm):
    def __init__(self, *args, academy=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.academy = academy
        self.fields['parent'].queryset = (
            scope_categories(Category.objects.filter(is_active=True), academy)
            if academy else Category.objects.none()
        )

    def clean_name(self):
        name = ' '.join((self.cleaned_data.get('name') or '').split()).strip()
        if not name:
            return name
        if self.academy and scope_categories(Category.objects.all(), self.academy).filter(name__iexact=name).exists():
            raise forms.ValidationError('Esta categoría ya existe. Selecciónala al crear o editar el curso.')
        return name

    class Meta:
        model = Category
        fields = ('name', 'description', 'parent')
        labels = {
            'name': 'Nombre de la categoría',
            'description': 'Descripción breve',
            'parent': 'Categoría superior (opcional)',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ej. Marketing Digital'}),
            'description': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Una descripción corta para organizar los cursos.'}),
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
    """Editor guiado de secciones dentro de un módulo."""

    SECTION_VIDEO = 'VIDEO'
    SECTION_PDF = 'PDF'
    SECTION_INSTRUCTIONS = 'INSTRUCTIONS'
    SECTION_CHOICES = [
        (SECTION_VIDEO, 'Video'),
        (SECTION_PDF, 'PDF'),
        (SECTION_INSTRUCTIONS, 'Indicaciones'),
    ]

    section_type = forms.ChoiceField(
        choices=SECTION_CHOICES,
        label='Tipo de sección',
        help_text='Elige un solo tipo principal para mantener el módulo ordenado y fácil de seguir.',
    )

    def clean_material_pdf(self):
        upload = self.cleaned_data.get('material_pdf')
        if not upload:
            return upload
        if (
            getattr(self.instance, 'pk', None)
            and getattr(self.instance, 'material_pdf', None)
            and getattr(upload, 'name', None) == getattr(self.instance.material_pdf, 'name', None)
            and not getattr(upload, 'content_type', None)
        ):
            return upload
        try:
            optimized, info = optimize_pdf_upload(upload)
        except PDFMaterialError as exc:
            raise forms.ValidationError(str(exc)) from exc
        self.pdf_optimization_info = info
        return optimized

    def clean(self):
        cleaned = super().clean()
        section_type = cleaned.get('section_type')
        video_source = (cleaned.get('video_source') or '').strip()
        material_pdf = cleaned.get('material_pdf')
        description = (cleaned.get('description') or '').strip()

        if section_type == self.SECTION_VIDEO and not video_source:
            self.add_error('video_source', 'Agrega la URL o ID del video para esta sección.')
        elif section_type == self.SECTION_PDF:
            has_existing_pdf = bool(getattr(self.instance, 'pk', None) and getattr(self.instance, 'material_pdf', None))
            if not material_pdf and not has_existing_pdf:
                self.add_error('material_pdf', 'Sube el PDF correspondiente a esta sección.')
        elif section_type == self.SECTION_INSTRUCTIONS and not description:
            self.add_error('description', 'Escribe las indicaciones que verá el estudiante.')
        return cleaned

    class Meta:
        model = Lesson
        fields = ['title', 'video_source', 'material_pdf', 'duration_minutes', 'description']
        labels = {
            'title': 'Título de la sección',
            'video_source': 'Video de YouTube',
            'material_pdf': 'Archivo PDF',
            'duration_minutes': 'Duración aproximada',
            'description': 'Indicaciones / texto de apoyo',
        }
        help_texts = {
            'video_source': 'Pega la URL o el ID de YouTube.',
            'material_pdf': 'El PDF se optimiza sin convertirlo a texto y se mantiene protegido dentro del curso.',
            'duration_minutes': 'Se usa en videos y PDFs para orientar al estudiante.',
            'description': 'En una sección de Indicaciones este campo es obligatorio. En video o PDF puedes usarlo como nota breve.',
        }
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': 'Ej. Introducción al módulo'}),
            'video_source': forms.TextInput(attrs={'placeholder': 'https://www.youtube.com/watch?v=...'}),
            'material_pdf': forms.ClearableFileInput(attrs={'accept': '.pdf,application/pdf'}),
            'duration_minutes': forms.NumberInput(attrs={'min': 0, 'placeholder': '15'}),
            'description': forms.Textarea(attrs={'placeholder': 'Escribe las indicaciones o una nota breve de apoyo', 'rows': 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            if getattr(self.instance, 'pk', None):
                if self.instance.video_source:
                    self.fields['section_type'].initial = self.SECTION_VIDEO
                elif self.instance.material_pdf:
                    self.fields['section_type'].initial = self.SECTION_PDF
                else:
                    self.fields['section_type'].initial = self.SECTION_INSTRUCTIONS
            else:
                self.fields['section_type'].initial = self.SECTION_VIDEO
                self.fields['duration_minutes'].initial = 15

    def save(self, commit=True):
        lesson = super().save(commit=False)
        section_type = self.cleaned_data.get('section_type')
        if section_type == self.SECTION_VIDEO:
            lesson.material_pdf = None
            lesson.video_provider = Lesson.VideoProvider.YOUTUBE
        elif section_type == self.SECTION_PDF:
            lesson.video_source = ''
            lesson.video_provider = Lesson.VideoProvider.NONE
        else:
            lesson.video_source = ''
            lesson.video_provider = Lesson.VideoProvider.NONE
            lesson.material_pdf = None
            lesson.duration_minutes = 0
        if commit:
            lesson.save()
            self.save_m2m()
        return lesson


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


class ProfessorCertificateToggleForm(forms.Form):
    """El profesor solo decide si el curso entrega certificado.

    El diseño, textos, colores, firma y demás parámetros pertenecen a la
    configuración de la academia y los administra exclusivamente el dueño.
    """
    certificate_enabled = forms.ChoiceField(
        choices=[('1', 'Sí'), ('0', 'No')],
        label='¿Este curso entrega certificado?',
        help_text='El diseño del certificado lo configura el dueño de la academia.',
        widget=forms.Select(attrs={'class': 'certificate-simple-select'}),
    )

    def __init__(self, *args, course=None, **kwargs):
        self.course = course
        if course is not None and 'initial' not in kwargs:
            kwargs['initial'] = {'certificate_enabled': '1' if course.certificate_enabled else '0'}
        super().__init__(*args, **kwargs)

    def clean_certificate_enabled(self):
        value = self.cleaned_data['certificate_enabled']
        if value == '0' and self.course and self.course.access_type == Course.AccessType.UNTIL_CERTIFICATE:
            raise forms.ValidationError(
                'Este curso usa acceso “Hasta certificarse”. Cambia primero el tipo de acceso en Ajustes del curso.'
            )
        return value

    def save(self):
        if self.course is None:
            raise ValueError('ProfessorCertificateToggleForm requiere un curso.')
        self.course.certificate_enabled = self.cleaned_data['certificate_enabled'] == '1'
        # El profesor nunca selecciona ni personaliza el estilo: siempre usa el
        # diseño central definido por el dueño de la academia.
        self.course.certificate_style_mode = Course.CertificateStyleMode.ACADEMY
        self.course.save(update_fields=['certificate_enabled', 'certificate_style_mode', 'updated_at'])
        return self.course
