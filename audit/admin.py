from django.contrib import admin
from .models import AuditLog

# Etiquetas del panel en español.
AuditLog._meta.verbose_name = 'registro de auditoría'
AuditLog._meta.verbose_name_plural = 'registros de auditoría'

for _field, _label in {'actor':'usuario','action':'acción','target_model':'modelo afectado','target_id':'identificador','metadata':'detalle','ip_address':'dirección IP','created_at':'fecha'}.items():
    AuditLog._meta.get_field(_field).verbose_name = _label

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'actor', 'action', 'target_model', 'target_id', 'ip_address')
    list_filter = ('action', 'target_model')
    search_fields = ('actor__email', 'action', 'target_id')
    readonly_fields = ('actor', 'action', 'target_model', 'target_id', 'metadata', 'ip_address', 'created_at')
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
