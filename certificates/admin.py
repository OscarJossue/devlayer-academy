from django.contrib import admin
from django.utils import timezone
from .models import Certificate

# Etiquetas del panel en español.
Certificate._meta.verbose_name = 'certificado'
Certificate._meta.verbose_name_plural = 'certificados'

for _field, _label in {'enrollment':'matrícula','code':'código','status':'estado','issued_at':'fecha de emisión','revoked_at':'fecha de revocación','revoked_reason':'motivo de revocación','issued_by':'emitido por'}.items():
    Certificate._meta.get_field(_field).verbose_name = _label

@admin.action(description='Revocar certificados seleccionados')
def revoke(modeladmin, request, queryset):
    queryset.update(status=Certificate.Status.REVOKED, revoked_at=timezone.now(), revoked_reason='Revocado por superadministrador')

@admin.register(Certificate)
class CertificateAdmin(admin.ModelAdmin):
    list_display = ('code', 'enrollment', 'status', 'issued_at', 'revoked_at')
    list_filter = ('status', 'enrollment__course')
    search_fields = ('code', 'enrollment__user__email', 'enrollment__course__title')
    actions = [revoke]
    readonly_fields = ('code', 'issued_at')
