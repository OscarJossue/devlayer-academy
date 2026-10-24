from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from accounts.models import User
from billing.models import BankAccount
from catalog.models import Category, Course
from learning.models import Enrollment
from tenancy.models import Academy, AcademyMembership
from tenancy.services import scope_categories, scope_courses


class SuperadminUserCreationForm(forms.Form):
    email = forms.EmailField(label='Correo electrónico', widget=forms.EmailInput(attrs={'placeholder': 'usuario@correo.com'}))
    first_name = forms.CharField(label='Nombre', max_length=150, widget=forms.TextInput(attrs={'placeholder': 'Nombre del usuario'}))
    last_name = forms.CharField(label='Apellido', max_length=150, widget=forms.TextInput(attrs={'placeholder': 'Apellido del usuario'}))
    phone = forms.CharField(label='Teléfono', max_length=30, required=False, widget=forms.TextInput(attrs={'placeholder': '+593 ...'}))
    role = forms.ChoiceField(label='Rol en esta academia', choices=[
        (AcademyMembership.Role.STUDENT, 'Estudiante'),
        (AcademyMembership.Role.PROFESSOR, 'Profesor'),
        (AcademyMembership.Role.ADMIN, 'Administrador'),
    ])
    email_verified = forms.BooleanField(label='Correo verificado', required=False)
    password1 = forms.CharField(label='Contraseña inicial', required=False, strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password', 'placeholder': 'Obligatoria solo si el correo es nuevo'}))
    password2 = forms.CharField(label='Confirmar contraseña', required=False, strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password', 'placeholder': 'Repite la contraseña'}))

    def __init__(self, *args, academy=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.academy = academy
        self.existing_user = None

    def clean_email(self):
        email = self.cleaned_data['email'].lower().strip()
        self.existing_user = User.objects.filter(email=email).first()
        if self.existing_user and self.academy and AcademyMembership.objects.filter(academy=self.academy, user_id=self.existing_user.pk).exists():
            raise forms.ValidationError('Ese usuario ya pertenece a esta academia.')
        return email

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get('password1'), cleaned.get('password2')
        if self.existing_user:
            return cleaned
        if not p1:
            self.add_error('password1', 'La contraseña es obligatoria para un correo nuevo.')
            return cleaned
        if p1 != p2:
            self.add_error('password2', 'Las contraseñas no coinciden.')
            return cleaned
        candidate = User(email=cleaned.get('email', ''), first_name=cleaned.get('first_name', ''), last_name=cleaned.get('last_name', ''))
        try:
            validate_password(p1, candidate)
        except ValidationError as exc:
            self.add_error('password1', exc)
        return cleaned

    def save(self, academy, approved_by=None):
        user = self.existing_user
        created = False
        if user is None:
            user = User.objects.create_user(
                email=self.cleaned_data['email'],
                password=self.cleaned_data['password1'],
                first_name=self.cleaned_data['first_name'],
                last_name=self.cleaned_data['last_name'],
                phone=self.cleaned_data.get('phone', ''),
                role=User.Role.STUDENT,
                email_verified=self.cleaned_data.get('email_verified', False),
                is_active=True,
            )
            created = True
        membership = AcademyMembership.objects.create(
            academy=academy,
            user_id=user.pk,
            role=self.cleaned_data['role'],
            status=AcademyMembership.Status.ACTIVE,
            approved_by_id=getattr(approved_by, 'pk', None),
        )
        from django.utils import timezone
        membership.approved_at = timezone.now()
        membership.save(update_fields=['approved_at'])
        return user, membership, created


class CategoryForm(forms.ModelForm):
    def __init__(self, *args, academy=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.academy = academy
        self.fields['parent'].queryset = scope_categories(Category.objects.all(), academy) if academy else Category.objects.none()

    class Meta:
        model = Category
        fields = ('name', 'description', 'parent', 'is_active', 'order')
        labels = {'name': 'Nombre de la categoría', 'description': 'Descripción', 'parent': 'Categoría superior', 'is_active': 'Activa', 'order': 'Orden'}
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ej. Desarrollo web'}),
            'description': forms.Textarea(attrs={'placeholder': 'Descripción breve para organizar el catálogo', 'rows': 3}),
            'order': forms.NumberInput(attrs={'min': 0, 'placeholder': '0'}),
        }

    def clean_name(self):
        name = ' '.join((self.cleaned_data.get('name') or '').split()).strip()
        if not name:
            return name
        if self.academy and scope_categories(Category.objects.all(), self.academy).filter(name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Ya existe una categoría con este nombre en la academia.')
        return name


class BankAccountForm(forms.ModelForm):
    class Meta:
        model = BankAccount
        fields = ('bank_name', 'account_type', 'account_number', 'holder_name', 'holder_id', 'instructions', 'is_active', 'order')
        labels = {'bank_name': 'Banco', 'account_type': 'Tipo de cuenta', 'account_number': 'Número de cuenta', 'holder_name': 'Titular', 'holder_id': 'Identificación', 'instructions': 'Instrucciones para el estudiante', 'is_active': 'Mostrar al estudiante', 'order': 'Orden'}
        widgets = {
            'bank_name': forms.TextInput(attrs={'placeholder': 'Ej. Banco Pichincha'}),
            'account_type': forms.TextInput(attrs={'placeholder': 'Ahorros / Corriente'}),
            'account_number': forms.TextInput(attrs={'placeholder': 'Número de cuenta'}),
            'holder_name': forms.TextInput(attrs={'placeholder': 'Nombre del titular'}),
            'holder_id': forms.TextInput(attrs={'placeholder': 'Cédula o RUC'}),
            'instructions': forms.Textarea(attrs={'placeholder': 'Indicaciones adicionales para realizar la transferencia', 'rows': 3}),
            'order': forms.NumberInput(attrs={'min': 0, 'placeholder': '0'}),
        }


class EnrollmentEditForm(forms.ModelForm):
    class Meta:
        model = Enrollment
        fields = ('status', 'starts_at', 'expires_at', 'blocked_reason', 'override_post_certificate_policy', 'override_post_certificate_days')
        labels = {'status': 'Estado del acceso', 'starts_at': 'Inicio', 'expires_at': 'Vence', 'blocked_reason': 'Motivo del bloqueo', 'override_post_certificate_policy': 'Regla después de certificar', 'override_post_certificate_days': 'Días adicionales'}
        widgets = {'starts_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}), 'expires_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}), 'blocked_reason': forms.TextInput(attrs={'placeholder': 'Solo si el acceso está bloqueado'})}


class EnrollmentCreateForm(forms.Form):
    student = forms.ModelChoiceField(label='Estudiante', queryset=User.objects.none(), empty_label='Selecciona un estudiante')
    course = forms.ModelChoiceField(label='Curso', queryset=Course.objects.none(), empty_label='Selecciona un curso')
    starts_at = forms.DateTimeField(
        label='Inicio del acceso', required=False,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        help_text='Si lo dejas vacío, el acceso inicia ahora.',
    )
    expires_at = forms.DateTimeField(
        label='Fecha de vencimiento', required=False,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        help_text='Opcional. Si queda vacío se usará la política del curso.',
    )

    def __init__(self, *args, academy=None, fixed_course=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.academy = academy
        self.fixed_course = fixed_course
        if not academy:
            return
        student_ids = AcademyMembership.objects.filter(
            academy=academy,
            role=AcademyMembership.Role.STUDENT,
            status=AcademyMembership.Status.ACTIVE,
        ).values_list('user_id', flat=True)
        self.fields['student'].queryset = User.objects.filter(pk__in=student_ids, is_active=True).order_by('first_name', 'last_name', 'email')
        self.fields['course'].queryset = scope_courses(Course.objects.all(), academy).order_by('title')
        if fixed_course is not None:
            self.fields['course'].queryset = self.fields['course'].queryset.filter(pk=fixed_course.pk)
            self.fields['course'].initial = fixed_course
            self.fields['course'].widget = forms.HiddenInput()

    def clean(self):
        cleaned = super().clean()
        student = cleaned.get('student')
        course = cleaned.get('course')
        if student and course and Enrollment.objects.filter(user=student, course=course).exists():
            self.add_error('student', 'Este estudiante ya tiene un acceso registrado para el curso seleccionado.')
        return cleaned

    def save(self):
        from django.utils import timezone
        student = self.cleaned_data['student']
        course = self.cleaned_data['course']
        enrollment = Enrollment(
            user=student,
            course=course,
            source=Enrollment.Source.ADMIN,
            status=Enrollment.Status.ACTIVE,
            starts_at=self.cleaned_data.get('starts_at') or timezone.now(),
        )
        if self.cleaned_data.get('expires_at'):
            enrollment.expires_at = self.cleaned_data['expires_at']
        else:
            enrollment.configure_default_expiry()
        enrollment.save()
        return enrollment


class AcademyBrandingForm(forms.ModelForm):
    class Meta:
        model = Academy
        fields = ('logo', 'brand_color', 'tagline', 'public_description', 'contact_email', 'phone')
        labels = {
            'logo': 'Logo',
            'brand_color': 'Color principal',
            'tagline': 'Frase principal',
            'public_description': 'Descripción pública',
            'contact_email': 'Correo de contacto',
            'phone': 'Teléfono de contacto',
        }
        widgets = {
            'logo': forms.FileInput(attrs={'accept': 'image/png,image/jpeg,image/webp'}),
            'brand_color': forms.TextInput(attrs={'type': 'color'}),
            'tagline': forms.TextInput(attrs={'placeholder': 'Ej. Aprende tecnología con nosotros'}),
            'public_description': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Descripción breve que verán los visitantes del catálogo.'}),
            'contact_email': forms.EmailInput(attrs={'placeholder': 'contacto@academia.com'}),
            'phone': forms.TextInput(attrs={'placeholder': '+593 ...'}),
        }

    def clean_logo(self):
        logo = self.cleaned_data.get('logo')
        if logo and getattr(logo, 'size', 0) > 3 * 1024 * 1024:
            raise forms.ValidationError('El logo no puede superar 3 MB.')
        return logo

    def clean_brand_color(self):
        value = (self.cleaned_data.get('brand_color') or '#1458D6').strip().upper()
        if len(value) != 7 or not value.startswith('#'):
            raise forms.ValidationError('Usa un color hexadecimal válido.')
        try:
            int(value[1:], 16)
        except ValueError:
            raise forms.ValidationError('Usa un color hexadecimal válido.')
        return value


class AcademySupportSettingsForm(forms.ModelForm):
    class Meta:
        model = Academy
        fields = (
            'support_title',
            'support_whatsapp_1_label', 'support_whatsapp_1_number',
            'support_whatsapp_2_label', 'support_whatsapp_2_number',
        )
        labels = {
            'support_title': 'Nombre del panel de soporte',
            'support_whatsapp_1_label': 'Etiqueta del contacto 1',
            'support_whatsapp_1_number': 'Número de WhatsApp 1',
            'support_whatsapp_2_label': 'Etiqueta del contacto 2',
            'support_whatsapp_2_number': 'Número de WhatsApp 2',
        }
        widgets = {
            'support_title': forms.TextInput(attrs={'placeholder': 'Ej. Soporte Academia Horizonte'}),
            'support_whatsapp_1_label': forms.TextInput(attrs={'placeholder': 'Ej. Soporte técnico'}),
            'support_whatsapp_1_number': forms.TextInput(attrs={'placeholder': '593999999999'}),
            'support_whatsapp_2_label': forms.TextInput(attrs={'placeholder': 'Ej. Contabilidad'}),
            'support_whatsapp_2_number': forms.TextInput(attrs={'placeholder': '593988888888'}),
        }
        help_texts = {
            'support_title': 'Este texto lo verán estudiantes y profesores encima de los contactos de WhatsApp.',
            'support_whatsapp_1_number': 'Código de país + número, sin +, espacios ni guiones.',
            'support_whatsapp_2_number': 'Opcional. Código de país + número, sin +, espacios ni guiones.',
        }

    def _clean_number(self, field_name):
        value = ''.join(ch for ch in (self.cleaned_data.get(field_name) or '') if ch.isdigit())
        if value and len(value) < 8:
            raise forms.ValidationError('Ingresa un número de WhatsApp válido con código de país.')
        return value

    def clean_support_whatsapp_1_number(self):
        return self._clean_number('support_whatsapp_1_number')

    def clean_support_whatsapp_2_number(self):
        return self._clean_number('support_whatsapp_2_number')

    def clean(self):
        cleaned = super().clean()
        for index in (1, 2):
            number = cleaned.get(f'support_whatsapp_{index}_number')
            label = (cleaned.get(f'support_whatsapp_{index}_label') or '').strip()
            if number and not label:
                cleaned[f'support_whatsapp_{index}_label'] = 'Soporte' if index == 1 else 'Atención'
            if label and not number:
                self.add_error(f'support_whatsapp_{index}_number', 'Ingresa el número correspondiente a esta etiqueta.')
        if not (cleaned.get('support_title') or '').strip():
            cleaned['support_title'] = 'Soporte de la academia'
        return cleaned


class AcademyPaymentSettingsForm(forms.ModelForm):
    class Meta:
        model = Academy
        fields = (
            'payment_transfer_enabled',
            'payment_paypal_enabled', 'payment_paypal_email', 'payment_paypal_url',
            'payment_payphone_enabled', 'payment_payphone_reference', 'payment_payphone_url',
            'payment_card_enabled', 'payment_card_instructions',
            'payment_link_1_enabled', 'payment_link_1_label', 'payment_link_1_url',
            'payment_link_2_enabled', 'payment_link_2_label', 'payment_link_2_url',
            'payment_whatsapp_enabled', 'payment_whatsapp_number',
            'payment_instructions',
        )
        labels = {
            'payment_transfer_enabled': 'Aceptar transferencias bancarias',
            'payment_paypal_enabled': 'Aceptar PayPal',
            'payment_paypal_email': 'Correo / cuenta de PayPal',
            'payment_paypal_url': 'Enlace de PayPal',
            'payment_payphone_enabled': 'Aceptar PayPhone',
            'payment_payphone_reference': 'Número o referencia de PayPhone',
            'payment_payphone_url': 'Enlace de PayPhone',
            'payment_card_enabled': 'Aceptar tarjeta mediante link por WhatsApp',
            'payment_card_instructions': 'Indicaciones para tarjeta',
            'payment_link_1_enabled': 'Habilitar link de pago 1',
            'payment_link_1_label': 'Nombre del link 1',
            'payment_link_1_url': 'URL del link 1',
            'payment_link_2_enabled': 'Habilitar link de pago 2',
            'payment_link_2_label': 'Nombre del link 2',
            'payment_link_2_url': 'URL del link 2',
            'payment_whatsapp_enabled': 'Mostrar WhatsApp para pagos y comprobantes',
            'payment_whatsapp_number': 'Número de WhatsApp para pagos',
            'payment_instructions': 'Indicaciones generales de pago',
        }
        widgets = {
            'payment_paypal_email': forms.EmailInput(attrs={'placeholder': 'pagos@academia.com'}),
            'payment_paypal_url': forms.URLInput(attrs={'placeholder': 'https://paypal.me/...'}),
            'payment_payphone_reference': forms.TextInput(attrs={'placeholder': 'Ej. 0987654321 o cuenta PayPhone'}),
            'payment_payphone_url': forms.URLInput(attrs={'placeholder': 'https://payphone.app/...'}),
            'payment_card_instructions': forms.TextInput(attrs={'placeholder': 'Solicita tu link de pago por WhatsApp.'}),
            'payment_link_1_label': forms.TextInput(attrs={'placeholder': 'Ej. Link de pago Produbanco'}),
            'payment_link_1_url': forms.URLInput(attrs={'placeholder': 'https://...'}),
            'payment_link_2_label': forms.TextInput(attrs={'placeholder': 'Ej. Link de pago alternativo'}),
            'payment_link_2_url': forms.URLInput(attrs={'placeholder': 'https://...'}),
            'payment_whatsapp_number': forms.TextInput(attrs={'placeholder': '593999999999'}),
            'payment_instructions': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Ej. Coloca el número de orden en la referencia de tu pago.',
            }),
        }
        help_texts = {
            'payment_whatsapp_number': 'Código de país + número, sin +, espacios ni guiones. Si se deja vacío, se usa un contacto de soporte de la academia.',
            'payment_card_enabled': 'El estudiante verá un botón para solicitar por WhatsApp un link seguro de pago con tarjeta.',
        }

    @staticmethod
    def _digits(value):
        return ''.join(ch for ch in (value or '') if ch.isdigit())

    def clean_payment_whatsapp_number(self):
        value = self._digits(self.cleaned_data.get('payment_whatsapp_number'))
        if value and len(value) < 8:
            raise forms.ValidationError('Ingresa un número de WhatsApp válido con código de país.')
        return value

    def clean(self):
        cleaned = super().clean()
        enabled = [
            cleaned.get('payment_transfer_enabled'), cleaned.get('payment_paypal_enabled'),
            cleaned.get('payment_payphone_enabled'), cleaned.get('payment_card_enabled'),
            cleaned.get('payment_link_1_enabled'), cleaned.get('payment_link_2_enabled'),
            cleaned.get('payment_whatsapp_enabled'),
        ]
        if not any(enabled):
            raise forms.ValidationError('Habilita al menos un método de pago para los cursos de pago.')

        if cleaned.get('payment_paypal_enabled') and not (cleaned.get('payment_paypal_email') or cleaned.get('payment_paypal_url')):
            self.add_error('payment_paypal_email', 'Configura un correo o un enlace de PayPal.')
        if cleaned.get('payment_payphone_enabled') and not (cleaned.get('payment_payphone_reference') or cleaned.get('payment_payphone_url')):
            self.add_error('payment_payphone_reference', 'Configura una referencia o un enlace de PayPhone.')

        for index in (1, 2):
            enabled_field = f'payment_link_{index}_enabled'
            label_field = f'payment_link_{index}_label'
            url_field = f'payment_link_{index}_url'
            if cleaned.get(enabled_field):
                if not (cleaned.get(label_field) or '').strip():
                    self.add_error(label_field, 'Pon un nombre para identificar este link de pago.')
                if not cleaned.get(url_field):
                    self.add_error(url_field, 'Ingresa la URL del link de pago.')

        if cleaned.get('payment_card_enabled'):
            has_whatsapp = bool(
                self._digits(cleaned.get('payment_whatsapp_number'))
                or self._digits(getattr(self.instance, 'support_whatsapp_1_number', ''))
                or self._digits(getattr(self.instance, 'support_whatsapp_2_number', ''))
            )
            if not has_whatsapp:
                self.add_error('payment_whatsapp_number', 'Para cobrar con tarjeta por link necesitas un WhatsApp de pagos o un contacto de soporte configurado.')

        return cleaned


class AcademySMTPForm(forms.Form):
    smtp_host = forms.CharField(
        label='Servidor SMTP', max_length=255,
        widget=forms.TextInput(attrs={'placeholder': 'mail.tudominio.com'}),
    )
    smtp_port = forms.ChoiceField(
        label='Puerto',
        choices=[('465', '465 · SSL'), ('587', '587 · STARTTLS')],
        initial='465',
        help_text='Selecciona el puerto indicado por tu proveedor de correo.',
    )
    smtp_username = forms.EmailField(
        label='Usuario / correo SMTP',
        widget=forms.EmailInput(attrs={'placeholder': 'academia@tudominio.com'}),
    )
    smtp_password = forms.CharField(
        label='Contraseña SMTP', required=False, strip=False,
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Déjala vacía para conservar la contraseña actual',
            'autocomplete': 'new-password',
        }),
    )
    smtp_from_name = forms.CharField(
        label='Nombre con el que se enviará el correo', max_length=160,
        widget=forms.TextInput(attrs={'placeholder': 'Ej. Academia Horizonte'}),
    )
    test_email = forms.EmailField(
        label='Correo para enviar una prueba', required=False,
        widget=forms.EmailInput(attrs={'placeholder': 'tu-correo@dominio.com'}),
        help_text='Solo se usa cuando pulsas “Guardar y enviar prueba”. No se guarda en la academia.',
    )

    def __init__(self, *args, academy=None, **kwargs):
        self.academy = academy
        if academy and not args and 'initial' not in kwargs:
            kwargs['initial'] = {
                'smtp_host': academy.smtp_host,
                'smtp_port': str(academy.smtp_port or (465 if academy.smtp_use_ssl else 587)),
                'smtp_username': academy.smtp_username or academy.smtp_from_email,
                'smtp_from_name': academy.smtp_from_name or academy.name,
            }
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('smtp_password') and not (self.academy and self.academy.smtp_password):
            self.add_error('smtp_password', 'Ingresa la contraseña SMTP la primera vez que configures el correo.')
        if self.data.get('action') == 'test' and not cleaned.get('test_email'):
            self.add_error('test_email', 'Indica el correo al que quieres enviar la prueba.')
        return cleaned

    def save(self):
        academy = self.academy
        port = int(self.cleaned_data['smtp_port'])
        username = self.cleaned_data['smtp_username'].strip()
        academy.smtp_enabled = True
        academy.smtp_host = self.cleaned_data['smtp_host'].strip()
        academy.smtp_port = port
        academy.smtp_username = username
        if self.cleaned_data.get('smtp_password'):
            academy.smtp_password = self.cleaned_data['smtp_password']
        academy.smtp_from_email = username
        academy.smtp_from_name = self.cleaned_data['smtp_from_name'].strip()
        academy.smtp_use_ssl = port == 465
        academy.smtp_use_tls = port == 587
        academy.save(update_fields=[
            'smtp_enabled', 'smtp_host', 'smtp_port', 'smtp_username', 'smtp_password',
            'smtp_from_email', 'smtp_from_name', 'smtp_use_tls', 'smtp_use_ssl', 'updated_at',
        ])
        return academy


class AcademyCertificateStyleForm(forms.ModelForm):
    class Meta:
        model = Academy
        fields = (
            'certificate_title', 'certificate_subtitle', 'certificate_body',
            'certificate_accent_color', 'certificate_background_color', 'certificate_text_color',
            'certificate_signature_name', 'certificate_signature_role', 'certificate_signature_image',
            'certificate_footer', 'certificate_show_logo', 'certificate_show_qr',
        )
        labels = {
            'certificate_title': 'Título principal',
            'certificate_subtitle': 'Texto antes del nombre del estudiante',
            'certificate_body': 'Texto antes del nombre del curso',
            'certificate_accent_color': 'Color de acento',
            'certificate_background_color': 'Color de fondo',
            'certificate_text_color': 'Color del texto',
            'certificate_signature_name': 'Nombre de quien firma',
            'certificate_signature_role': 'Cargo de quien firma',
            'certificate_signature_image': 'Firma (imagen opcional)',
            'certificate_footer': 'Texto inferior',
            'certificate_show_logo': 'Mostrar logo de la academia',
            'certificate_show_qr': 'Mostrar QR de validación',
        }
        widgets = {
            'certificate_title': forms.TextInput(attrs={'placeholder': 'Certificado de finalización'}),
            'certificate_subtitle': forms.TextInput(attrs={'placeholder': 'Se certifica que'}),
            'certificate_body': forms.TextInput(attrs={'placeholder': 'ha completado satisfactoriamente el curso'}),
            'certificate_accent_color': forms.TextInput(attrs={'type': 'color'}),
            'certificate_background_color': forms.TextInput(attrs={'type': 'color'}),
            'certificate_text_color': forms.TextInput(attrs={'type': 'color'}),
            'certificate_signature_name': forms.TextInput(attrs={'placeholder': 'Nombre y apellido'}),
            'certificate_signature_role': forms.TextInput(attrs={'placeholder': 'Director académico'}),
            'certificate_signature_image': forms.FileInput(attrs={'accept': 'image/png,image/jpeg,image/webp'}),
            'certificate_footer': forms.TextInput(attrs={'placeholder': 'Certificado verificable digitalmente.'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance:
            if not self.instance.certificate_accent_color:
                self.initial['certificate_accent_color'] = self.instance.brand_color or '#1458D6'
            if not self.instance.certificate_background_color:
                self.initial['certificate_background_color'] = '#FFFFFF'
            if not self.instance.certificate_text_color:
                self.initial['certificate_text_color'] = '#172033'

    def clean_certificate_accent_color(self):
        value = (self.cleaned_data.get('certificate_accent_color') or self.instance.brand_color or '#1458D6').upper()
        return self._hex(value)

    def clean_certificate_background_color(self):
        return self._hex((self.cleaned_data.get('certificate_background_color') or '#FFFFFF').upper())

    def clean_certificate_text_color(self):
        return self._hex((self.cleaned_data.get('certificate_text_color') or '#172033').upper())

    @staticmethod
    def _hex(value):
        if len(value) != 7 or not value.startswith('#'):
            raise forms.ValidationError('Selecciona un color válido.')
        try:
            int(value[1:], 16)
        except ValueError as exc:
            raise forms.ValidationError('Selecciona un color válido.') from exc
        return value
