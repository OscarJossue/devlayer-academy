from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import Academy, AcademyLicense, AcademyMembership, AcademyPlan
from .services import bind_user

User = get_user_model()


class AcademyPlanForm(forms.ModelForm):
    class Meta:
        model = AcademyPlan
        fields = (
            'name', 'description', 'max_students', 'max_professors', 'max_admins',
            'price', 'currency', 'duration_days', 'is_active',
        )
        labels = {
            'name': 'Nombre del plan',
            'description': 'Descripción',
            'max_students': 'Máximo de estudiantes activos',
            'max_professors': 'Máximo de profesores',
            'max_admins': 'Máximo de administradores',
            'price': 'Precio del plan',
            'currency': 'Moneda',
            'duration_days': 'Duración de la licencia (días)',
            'is_active': 'Disponible para nuevas academias',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ej. Profesional'}),
            'description': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Qué incluye este plan y para qué tipo de academia está pensado.'}),
            'max_students': forms.NumberInput(attrs={'min': 0, 'placeholder': '100'}),
            'max_professors': forms.NumberInput(attrs={'min': 0, 'placeholder': '5'}),
            'max_admins': forms.NumberInput(attrs={'min': 0, 'placeholder': '2'}),
            'price': forms.NumberInput(attrs={'min': 0, 'step': '0.01', 'placeholder': '99.00'}),
            'currency': forms.TextInput(attrs={'placeholder': 'USD'}),
            'duration_days': forms.NumberInput(attrs={'min': 0, 'placeholder': '365'}),
        }
        help_texts = {
            'max_students': '0 = estudiantes ilimitados.',
            'max_professors': '0 = profesores ilimitados.',
            'max_admins': '0 = administradores ilimitados. El dueño no consume este cupo.',
            'duration_days': '0 = licencia sin vencimiento automático.',
        }

    def clean_currency(self):
        return (self.cleaned_data.get('currency') or 'USD').strip().upper()


class AcademyCreateForm(forms.Form):
    name = forms.CharField(
        label='Nombre comercial', max_length=180,
        widget=forms.TextInput(attrs={'placeholder': 'Ej. Nova Academy'}),
    )
    slug = forms.SlugField(
        label='Código / slug', max_length=190, required=False,
        widget=forms.TextInput(attrs={'placeholder': 'nova-academy'}),
        help_text='Se usará en /academy/slug/. Si lo dejas vacío se genera automáticamente.',
    )
    legal_name = forms.CharField(label='Razón social', max_length=220, required=False)
    tax_id = forms.CharField(label='RUC / identificación', max_length=60, required=False)
    contact_email = forms.EmailField(label='Correo administrativo', required=False)
    phone = forms.CharField(label='Teléfono', max_length=40, required=False)
    custom_domain = forms.CharField(
        label='Dominio propio (opcional)', max_length=255, required=False,
        widget=forms.TextInput(attrs={'placeholder': 'academia.cliente.com'}),
    )

    plan = forms.ModelChoiceField(
        label='Plan de licencia',
        queryset=AcademyPlan.objects.none(),
        empty_label='Selecciona un plan',
        help_text='El precio, duración y cupos se toman del plan seleccionado.',
    )
    starts_at = forms.DateField(
        label='Inicio de licencia', initial=timezone.localdate,
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    amount_paid = forms.DecimalField(
        label='Valor cobrado al crear la licencia', min_value=0, decimal_places=2,
        max_digits=12, initial=0,
        widget=forms.NumberInput(attrs={'step': '0.01', 'placeholder': '0.00'}),
    )
    notes = forms.CharField(
        label='Notas internas', required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Condiciones comerciales, forma de pago o referencia del cliente.'}),
    )

    owner_first_name = forms.CharField(
        label='Nombre del dueño', max_length=150,
        widget=forms.TextInput(attrs={'placeholder': 'Nombre del responsable principal'}),
    )
    owner_last_name = forms.CharField(
        label='Apellido del dueño', max_length=150,
        widget=forms.TextInput(attrs={'placeholder': 'Apellido del responsable principal'}),
    )
    owner_email = forms.EmailField(
        label='Correo de acceso del dueño',
        widget=forms.EmailInput(attrs={'placeholder': 'dueno@academia.com'}),
    )
    owner_password = forms.CharField(
        label='Contraseña inicial del dueño', min_length=8,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password', 'placeholder': 'Mínimo 8 caracteres'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['plan'].queryset = AcademyPlan.objects.filter(is_active=True).order_by('price', 'name')
        self.fields['plan'].label_from_instance = lambda obj: (
            f'{obj.name} — {obj.currency} {obj.price} — '
            f'{obj.max_students or "∞"} estudiantes / {obj.max_professors or "∞"} profesores / {obj.max_admins or "∞"} admins'
        )

    def clean_owner_email(self):
        return self.cleaned_data['owner_email'].lower().strip()

    def clean_custom_domain(self):
        value = (
            self.cleaned_data.get('custom_domain') or ''
        ).strip().lower().replace('https://', '').replace('http://', '').strip('/')
        if value and Academy.objects.filter(custom_domain=value).exists():
            raise forms.ValidationError('Ese dominio ya está asignado a otra academia.')
        return value or None

    def clean(self):
        cleaned = super().clean()
        plan = cleaned.get('plan')
        amount_paid = cleaned.get('amount_paid') or 0
        if plan and plan.price and amount_paid > plan.price:
            self.add_error('amount_paid', 'El valor cobrado no puede superar el precio del plan.')
        return cleaned

    @transaction.atomic
    def save(self):
        plan = self.cleaned_data['plan']
        starts_at = self.cleaned_data['starts_at']
        ends_at = starts_at + timedelta(days=plan.duration_days - 1) if plan.duration_days else None
        amount_paid = self.cleaned_data.get('amount_paid') or 0
        if plan.price == 0:
            financial_status = AcademyLicense.FinancialStatus.COURTESY
        elif amount_paid >= plan.price:
            financial_status = AcademyLicense.FinancialStatus.PAID
        elif amount_paid > 0:
            financial_status = AcademyLicense.FinancialStatus.PARTIAL
        else:
            financial_status = AcademyLicense.FinancialStatus.PENDING

        academy = Academy.objects.create(
            name=self.cleaned_data['name'],
            slug=self.cleaned_data.get('slug') or '',
            legal_name=self.cleaned_data.get('legal_name', ''),
            tax_id=self.cleaned_data.get('tax_id', ''),
            contact_email=self.cleaned_data.get('contact_email', ''),
            phone=self.cleaned_data.get('phone', ''),
            custom_domain=self.cleaned_data.get('custom_domain'),
            # La identidad visual la configura el dueño desde su academia.
            logo=None,
            brand_color='#1458D6',
            tagline='',
            public_description='',
            is_active=True,
        )
        AcademyLicense.objects.create(
            academy=academy,
            plan=plan,
            plan_name=plan.name,
            status=AcademyLicense.Status.ACTIVE,
            starts_at=starts_at,
            ends_at=ends_at,
            max_users=plan.max_students,
            max_professors=plan.max_professors,
            max_admins=plan.max_admins,
            price=plan.price,
            amount_paid=amount_paid,
            currency=plan.currency,
            financial_status=financial_status,
            notes=self.cleaned_data.get('notes', ''),
        )
        owner = User.objects.filter(email=self.cleaned_data['owner_email']).first()
        if owner is None:
            owner = User.objects.create_user(
                email=self.cleaned_data['owner_email'],
                password=self.cleaned_data['owner_password'],
                first_name=self.cleaned_data['owner_first_name'],
                last_name=self.cleaned_data['owner_last_name'],
                role=User.Role.STUDENT,
                email_verified=True,
                is_active=True,
            )
        bind_user(
            owner, academy,
            role=AcademyMembership.Role.OWNER,
            status=AcademyMembership.Status.ACTIVE,
        )
        return academy, owner


class AcademyEditForm(forms.ModelForm):
    """Datos contractuales que controla DevLayer. El branding pertenece al dueño."""
    class Meta:
        model = Academy
        fields = ('name', 'legal_name', 'tax_id', 'contact_email', 'phone', 'custom_domain', 'is_active')
        labels = {
            'name': 'Nombre comercial',
            'legal_name': 'Razón social',
            'tax_id': 'RUC / identificación',
            'contact_email': 'Correo administrativo',
            'phone': 'Teléfono',
            'custom_domain': 'Dominio propio',
            'is_active': 'Academia habilitada',
        }
        widgets = {
            'custom_domain': forms.TextInput(attrs={'placeholder': 'academia.cliente.com'}),
        }

    def clean_custom_domain(self):
        value = (self.cleaned_data.get('custom_domain') or '').strip().lower().replace('https://', '').replace('http://', '').strip('/')
        if value and Academy.objects.exclude(pk=self.instance.pk).filter(custom_domain=value).exists():
            raise forms.ValidationError('Ese dominio ya está asignado a otra academia.')
        return value or None


class LicenseForm(forms.ModelForm):
    plan = forms.ModelChoiceField(
        label='Plan comercial', queryset=AcademyPlan.objects.none(), required=False,
        empty_label='Plan heredado / personalizado',
        help_text='Al cambiar el plan se actualizan precio y límites con la configuración actual del plan.',
    )

    class Meta:
        model = AcademyLicense
        fields = ('plan', 'status', 'starts_at', 'ends_at', 'amount_paid', 'financial_status', 'notes')
        labels = {
            'status': 'Estado de acceso',
            'starts_at': 'Inicio',
            'ends_at': 'Vencimiento',
            'amount_paid': 'Valor cobrado',
            'financial_status': 'Estado financiero',
            'notes': 'Notas internas',
        }
        widgets = {
            'starts_at': forms.DateInput(attrs={'type': 'date'}),
            'ends_at': forms.DateInput(attrs={'type': 'date'}),
            'amount_paid': forms.NumberInput(attrs={'step': '0.01'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_plan_id = self.instance.plan_id if self.instance and self.instance.pk else None
        qs = AcademyPlan.objects.filter(is_active=True)
        if self.instance and self.instance.plan_id:
            qs = AcademyPlan.objects.filter(id=self.instance.plan_id) | qs
        self.fields['plan'].queryset = qs.distinct().order_by('price', 'name')
        self.fields['plan'].label_from_instance = lambda obj: (
            f'{obj.name} — {obj.currency} {obj.price} — '
            f'{obj.max_students or "∞"} estudiantes / {obj.max_professors or "∞"} profesores / {obj.max_admins or "∞"} admins'
        )

    def clean(self):
        cleaned = super().clean()
        starts_at = cleaned.get('starts_at')
        ends_at = cleaned.get('ends_at')
        plan = cleaned.get('plan')
        amount_paid = cleaned.get('amount_paid') or 0
        price = plan.price if plan else (self.instance.price or 0)
        if starts_at and ends_at and ends_at < starts_at:
            self.add_error('ends_at', 'La fecha de vencimiento no puede ser anterior al inicio.')
        if amount_paid > price and price > 0:
            self.add_error('amount_paid', 'El valor cobrado no puede superar el valor de la licencia.')
        return cleaned

    def save(self, commit=True):
        license_obj = super().save(commit=False)
        plan = self.cleaned_data.get('plan')
        if plan:
            old_plan_id = self._original_plan_id
            license_obj.plan = plan
            license_obj.plan_name = plan.name
            license_obj.max_users = plan.max_students
            license_obj.max_professors = plan.max_professors
            license_obj.max_admins = plan.max_admins
            license_obj.price = plan.price
            license_obj.currency = plan.currency
            if old_plan_id != plan.id and license_obj.starts_at and plan.duration_days:
                license_obj.ends_at = license_obj.starts_at + timedelta(days=plan.duration_days - 1)
            elif old_plan_id != plan.id and plan.duration_days == 0:
                license_obj.ends_at = None
        if commit:
            license_obj.save()
        return license_obj


class AcademyOwnerForm(forms.Form):
    first_name = forms.CharField(label='Nombre', max_length=150)
    last_name = forms.CharField(label='Apellido', max_length=150)
    email = forms.EmailField(label='Correo electrónico')
    password = forms.CharField(
        label='Contraseña inicial', min_length=8,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
    )

    def clean_email(self):
        return self.cleaned_data['email'].lower().strip()

    def save(self, academy):
        if AcademyMembership.objects.filter(academy=academy, role=AcademyMembership.Role.OWNER).exists():
            raise forms.ValidationError('Esta academia ya tiene un dueño asignado.')
        user = User.objects.filter(email=self.cleaned_data['email']).first()
        if user is None:
            user = User.objects.create_user(
                email=self.cleaned_data['email'],
                password=self.cleaned_data['password'],
                first_name=self.cleaned_data['first_name'],
                last_name=self.cleaned_data['last_name'],
                role=User.Role.STUDENT,
                email_verified=True,
                is_active=True,
            )
        bind_user(user, academy, role=AcademyMembership.Role.OWNER, status=AcademyMembership.Status.ACTIVE)
        return user


# Alias de compatibilidad para rutas o imports previos.
AcademySuperadminForm = AcademyOwnerForm
