from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from .models import User
from .forms import AcademyAdminUserCreationForm, AcademyAdminUserChangeForm
from .services import send_verification_email

# Etiquetas visibles del panel administrativo sin alterar la base de datos.
User._meta.verbose_name = 'usuario'
User._meta.verbose_name_plural = 'usuarios'
for field_name, label in {
    'email': 'correo electrónico',
    'role': 'rol',
    'email_verified': 'correo verificado',
    'phone': 'teléfono',
}.items():
    User._meta.get_field(field_name).verbose_name = label


@admin.action(description='Asignar rol Profesor')
def assign_professor(modeladmin, request, queryset):
    updated = queryset.exclude(is_superuser=True).update(role=User.Role.PROFESSOR)
    modeladmin.message_user(request, f'{updated} usuario(s) ahora tienen rol Profesor.', messages.SUCCESS)


@admin.action(description='Asignar rol Estudiante')
def assign_student(modeladmin, request, queryset):
    updated = queryset.exclude(is_superuser=True).update(role=User.Role.STUDENT, is_staff=False)
    modeladmin.message_user(request, f'{updated} usuario(s) ahora tienen rol Estudiante.', messages.SUCCESS)


@admin.action(description='Habilitar usuarios seleccionados')
def enable_users(modeladmin, request, queryset):
    updated = queryset.update(is_active=True)
    modeladmin.message_user(request, f'{updated} usuario(s) habilitados.', messages.SUCCESS)


@admin.action(description='Deshabilitar usuarios seleccionados')
def disable_users(modeladmin, request, queryset):
    updated = queryset.exclude(is_superuser=True).update(is_active=False)
    modeladmin.message_user(request, f'{updated} usuario(s) deshabilitados.', messages.WARNING)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User
    add_form = AcademyAdminUserCreationForm
    form = AcademyAdminUserChangeForm
    ordering = ('email',)
    list_display = ('email', 'name_column', 'role_column', 'email_verified', 'status_column', 'date_joined')
    list_filter = ('role', 'email_verified', 'is_active')
    search_fields = ('email', 'first_name', 'last_name', 'phone')
    actions = [assign_professor, assign_student, enable_users, disable_users]
    list_per_page = 30

    fieldsets = (
        ('Acceso', {'fields': ('email', 'password')}),
        ('Perfil y rol', {'fields': ('first_name', 'last_name', 'phone', 'role', 'email_verified')}),
        ('Estado de la cuenta', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
            'description': 'Desactiva “Activo” para impedir el acceso completo. El rol Profesor usa el panel académico y no necesita permiso de staff.',
        }),
        ('Fechas', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        ('Crear usuario', {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'phone', 'password1', 'password2', 'role', 'email_verified', 'is_active'),
            'description': 'Para crear un profesor selecciona “Profesor” en Rol. El usuario podrá entrar inmediatamente al panel del profesor si su cuenta está activa y el correo está verificado.',
        }),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change and not obj.email_verified:
            try:
                send_verification_email(request, obj)
                self.message_user(request, 'Usuario creado. Se envió el correo de verificación.', messages.SUCCESS)
            except Exception:
                self.message_user(request, 'Usuario creado, pero no se pudo enviar el correo de verificación. Revisa el SMTP o marca el correo como verificado manualmente.', messages.WARNING)

    @admin.display(description='Nombre')
    def name_column(self, obj):
        return obj.display_name

    @admin.display(description='Rol', ordering='role')
    def role_column(self, obj):
        styles = {
            User.Role.SUPERADMIN: ('#e9efff', '#2447a8'),
            User.Role.ADMIN: ('#edf5ff', '#246ca8'),
            User.Role.PROFESSOR: ('#eaf8f4', '#14715b'),
            User.Role.STUDENT: ('#f4f1ff', '#6243ad'),
        }
        bg, fg = styles.get(obj.role, ('#f0f2f5', '#4f596a'))
        return format_html('<span style="display:inline-block;padding:5px 8px;border-radius:6px;background:{};color:{};font-weight:700;font-size:11px">{}</span>', bg, fg, obj.get_role_display())

    @admin.display(description='Estado', ordering='is_active')
    def status_column(self, obj):
        if obj.is_active:
            return format_html('<span style="color:{};font-weight:700">{}</span>', '#15785d', 'Activo')
        return format_html('<span style="color:{};font-weight:700">{}</span>', '#b93850', 'Deshabilitado')
