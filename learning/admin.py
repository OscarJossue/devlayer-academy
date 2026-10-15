from django.contrib import admin
from .models import Enrollment, LessonProgress

# Etiquetas del panel en español.
Enrollment._meta.verbose_name = 'matrícula'
Enrollment._meta.verbose_name_plural = 'matrículas'
LessonProgress._meta.verbose_name = 'progreso de clase'
LessonProgress._meta.verbose_name_plural = 'progreso de clases'

for _model, _labels in {
    Enrollment: {'user':'estudiante','course':'curso','status':'estado','source':'origen','starts_at':'inicio del acceso','expires_at':'fin del acceso','blocked_reason':'motivo del bloqueo','certified_at':'fecha de certificación','override_post_certificate_policy':'regla especial después de certificar','override_post_certificate_days':'días especiales después de certificar'},
    LessonProgress: {'enrollment':'matrícula','lesson':'clase','started_at':'inicio','last_viewed_at':'última visualización','completed_at':'completada','views_count':'visualizaciones'},
}.items():
    for _field, _label in _labels.items():
        _model._meta.get_field(_field).verbose_name = _label

@admin.action(description='Bloquear cursos seleccionados')
def block_enrollments(modeladmin, request, queryset):
    queryset.update(status=Enrollment.Status.BLOCKED, blocked_reason='Bloqueado por superadministrador')

@admin.action(description='Desbloquear cursos seleccionados')
def unblock_enrollments(modeladmin, request, queryset):
    queryset.update(status=Enrollment.Status.ACTIVE, blocked_reason='')

@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ('user', 'course', 'status', 'source', 'starts_at', 'expires_at', 'certified_at')
    list_filter = ('status', 'source', 'course')
    search_fields = ('user__email', 'user__first_name', 'user__last_name', 'course__title')
    actions = [block_enrollments, unblock_enrollments]
    readonly_fields = ('access_token', 'created_at', 'updated_at')

@admin.register(LessonProgress)
class LessonProgressAdmin(admin.ModelAdmin):
    list_display = ('enrollment', 'lesson', 'completed_at', 'views_count', 'last_viewed_at')
    list_filter = ('lesson__module__course', 'completed_at')
