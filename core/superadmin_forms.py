from django import forms
from django.contrib.auth.forms import UserCreationForm

from accounts.models import User
from billing.models import BankAccount
from catalog.models import Category
from learning.models import Enrollment


class SuperadminUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ('email', 'first_name', 'last_name', 'phone', 'role', 'email_verified', 'is_active')
        labels = {
            'email': 'Correo electrónico',
            'first_name': 'Nombre',
            'last_name': 'Apellido',
            'phone': 'Teléfono',
            'role': 'Rol',
            'email_verified': 'Correo verificado',
            'is_active': 'Cuenta activa',
        }
        widgets = {
            'email': forms.EmailInput(attrs={'placeholder': 'profesor@correo.com'}),
            'first_name': forms.TextInput(attrs={'placeholder': 'Nombre del usuario'}),
            'last_name': forms.TextInput(attrs={'placeholder': 'Apellido del usuario'}),
            'phone': forms.TextInput(attrs={'placeholder': '+593 ...'}),
        }


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ('name', 'description', 'parent', 'is_active', 'order')
        labels = {
            'name': 'Nombre de la categoría',
            'description': 'Descripción',
            'parent': 'Categoría superior',
            'is_active': 'Activa',
            'order': 'Orden',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ej. Desarrollo web'}),
            'description': forms.Textarea(attrs={'placeholder': 'Descripción breve para organizar el catálogo', 'rows': 3}),
            'order': forms.NumberInput(attrs={'min': 0, 'placeholder': '0'}),
        }


class BankAccountForm(forms.ModelForm):
    class Meta:
        model = BankAccount
        fields = ('bank_name', 'account_type', 'account_number', 'holder_name', 'holder_id', 'instructions', 'is_active', 'order')
        labels = {
            'bank_name': 'Banco',
            'account_type': 'Tipo de cuenta',
            'account_number': 'Número de cuenta',
            'holder_name': 'Titular',
            'holder_id': 'Identificación',
            'instructions': 'Instrucciones para el estudiante',
            'is_active': 'Mostrar al estudiante',
            'order': 'Orden',
        }
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
        labels = {
            'status': 'Estado del acceso',
            'starts_at': 'Inicio',
            'expires_at': 'Vence',
            'blocked_reason': 'Motivo del bloqueo',
            'override_post_certificate_policy': 'Regla después de certificar',
            'override_post_certificate_days': 'Días adicionales',
        }
        widgets = {
            'starts_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'expires_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'blocked_reason': forms.TextInput(attrs={'placeholder': 'Solo si el acceso está bloqueado'}),
        }
