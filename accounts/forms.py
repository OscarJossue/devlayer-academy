from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, UserChangeForm, UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.template import loader
from django.core.mail import EmailMultiAlternatives

from tenancy.models import Academy, AcademyMembership
from tenancy.mail import academy_email_connection, attach_brand_logo
from .models import User


class RegisterForm(forms.Form):
    first_name = forms.CharField(label='Nombre', max_length=150, widget=forms.TextInput(attrs={'placeholder': 'Tu nombre'}))
    last_name = forms.CharField(label='Apellido', max_length=150, widget=forms.TextInput(attrs={'placeholder': 'Tu apellido'}))
    email = forms.EmailField(label='Correo electrónico', widget=forms.EmailInput(attrs={'placeholder': 'nombre@correo.com'}))
    phone = forms.CharField(label='Teléfono (opcional)', max_length=30, required=False, widget=forms.TextInput(attrs={'placeholder': '+593 ...'}))
    password1 = forms.CharField(label='Contraseña', strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password', 'placeholder': 'Crea una contraseña segura'}))
    password2 = forms.CharField(label='Confirmar contraseña', strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password', 'placeholder': 'Repite la contraseña'}))

    def __init__(self, *args, academy=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.academy = academy
        self.existing_user = None

    def clean_email(self):
        email = self.cleaned_data['email'].lower().strip()
        self.existing_user = User.objects.filter(email=email).first()
        if self.existing_user and self.academy and AcademyMembership.objects.filter(academy=self.academy, user_id=self.existing_user.pk).exists():
            raise forms.ValidationError('Este correo ya está registrado en esta academia. Usa Iniciar sesión.')
        return email

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get('password1')
        password2 = cleaned.get('password2')
        if password1 and password2 and password1 != password2:
            self.add_error('password2', 'Las contraseñas no coinciden.')
            return cleaned
        if password1:
            if self.existing_user:
                if not self.existing_user.check_password(password1):
                    self.add_error('password1', 'Ese correo ya existe en Devlayer Academy. Usa la contraseña de esa cuenta para solicitar acceso a esta academia.')
            else:
                candidate = User(
                    email=cleaned.get('email', ''), first_name=cleaned.get('first_name', ''),
                    last_name=cleaned.get('last_name', ''), phone=cleaned.get('phone', ''),
                )
                try:
                    validate_password(password1, candidate)
                except ValidationError as exc:
                    self.add_error('password1', exc)
        return cleaned

    def save(self):
        if self.existing_user:
            return self.existing_user, False
        user = User.objects.create_user(
            email=self.cleaned_data['email'],
            password=self.cleaned_data['password1'],
            first_name=self.cleaned_data['first_name'],
            last_name=self.cleaned_data['last_name'],
            phone=self.cleaned_data.get('phone', ''),
            role=User.Role.STUDENT,
            email_verified=False,
            is_active=True,
        )
        return user, True


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(
        label='Correo electrónico',
        widget=forms.EmailInput(attrs={'autofocus': True, 'placeholder': 'nombre@correo.com'}),
    )
    password = forms.CharField(
        label='Contraseña',
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'current-password', 'placeholder': 'Tu contraseña'}),
    )


class AcademyPasswordResetForm(PasswordResetForm):
    def __init__(self, *args, academy=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.academy = academy
        self.fields['email'].widget.attrs.update({'placeholder': 'nombre@correo.com'})

    def get_users(self, email):
        if not self.academy:
            return []
        ids = AcademyMembership.objects.filter(academy=self.academy).values_list('user_id', flat=True)
        return User.objects.filter(pk__in=ids, email__iexact=email, is_active=True)

    def send_mail(self, subject_template_name, email_template_name, context, from_email, to_email, html_email_template_name=None):
        if not self.academy or not self.academy.smtp_configured:
            raise RuntimeError('El SMTP de esta academia no está configurado.')
        subject = loader.render_to_string(subject_template_name, context)
        subject = ''.join(subject.splitlines())
        body = loader.render_to_string(email_template_name, context)
        connection = academy_email_connection(self.academy)
        email_message = EmailMultiAlternatives(
            subject,
            body,
            self.academy.smtp_sender,
            [to_email],
            connection=connection,
        )
        if html_email_template_name:
            html_email = loader.render_to_string(html_email_template_name, context)
            attach_brand_logo(email_message, self.academy)
            email_message.attach_alternative(html_email, 'text/html')
        email_message.send()


class AcademyAdminUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ('email', 'first_name', 'last_name', 'phone', 'role', 'email_verified', 'is_active')


class AcademyAdminUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = '__all__'
