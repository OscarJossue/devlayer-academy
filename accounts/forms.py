from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserChangeForm, UserCreationForm
from .models import User


class RegisterForm(UserCreationForm):
    first_name = forms.CharField(label='Nombre', max_length=150, widget=forms.TextInput(attrs={'placeholder': 'Tu nombre'}))
    last_name = forms.CharField(label='Apellido', max_length=150, widget=forms.TextInput(attrs={'placeholder': 'Tu apellido'}))

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'phone', 'password1', 'password2')
        labels = {'email': 'Correo electrónico', 'phone': 'Teléfono (opcional)'}
        widgets = {
            'email': forms.EmailInput(attrs={'placeholder': 'nombre@correo.com'}),
            'phone': forms.TextInput(attrs={'placeholder': '+593 ...'}),
        }


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


class AcademyAdminUserCreationForm(UserCreationForm):
    """Formulario seguro para que el superadministrador cree estudiantes o profesores."""

    class Meta:
        model = User
        fields = ('email', 'first_name', 'last_name', 'phone', 'role', 'email_verified', 'is_active')


class AcademyAdminUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = '__all__'
