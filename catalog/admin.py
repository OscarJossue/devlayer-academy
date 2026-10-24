from django.contrib import admin
from django.utils import timezone
from .models import Category, Course, CourseInstructor, Module, Lesson

# Etiquetas del panel en español.
for _model, _singular, _plural in [
    (Category, 'categoría', 'categorías'), (Course, 'curso', 'cursos'),
    (CourseInstructor, 'profesor del curso', 'profesores del curso'),
    (Module, 'módulo', 'módulos'), (Lesson, 'clase', 'clases'),
]:
    _model._meta.verbose_name = _singular
    _model._meta.verbose_name_plural = _plural

# Nombres de campos visibles en español.
for _model, _labels in {
    Category: {'name':'nombre','slug':'identificador URL','description':'descripción','parent':'categoría superior','is_active':'activa','order':'orden'},
    Course: {'title':'nombre del curso','slug':'identificador URL','short_description':'descripción corta','description':'descripción','category':'categoría','thumbnail':'portada','price':'precio normal','currency':'moneda','discount_enabled':'descuento activo','discount_type':'tipo de descuento','discount_value':'valor del descuento','discount_starts_at':'inicio de la oferta','discount_ends_at':'fin de la oferta','status':'estado','sequential_learning':'aprendizaje secuencial','default_pass_percentage':'nota mínima (%)','access_type':'tipo de acceso','access_days':'días de acceso','access_fixed_until':'fecha límite','post_certificate_policy':'acceso después de certificar','post_certificate_days':'días adicionales','final_exam_required':'examen final obligatorio','created_by':'creado por','approved_by':'aprobado por','approved_at':'fecha de aprobación','published_at':'fecha de publicación','created_at':'creado','updated_at':'actualizado'},
    CourseInstructor: {'course':'curso','user':'profesor','is_owner':'profesor principal','added_at':'asignado'},
    Module: {'course':'curso','title':'nombre','description':'descripción','order':'orden','is_published':'publicado','requires_quiz_to_unlock_next':'exige cuestionario para continuar'},
    Lesson: {'module':'módulo','title':'nombre','description':'descripción','order':'orden','duration_minutes':'duración (minutos)','video_provider':'tipo de video','video_source':'URL o ID del video','material_pdf':'material PDF','is_preview':'vista previa','is_published':'publicada'},
}.items():
    for _field, _label in _labels.items():
        _model._meta.get_field(_field).verbose_name = _label

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent', 'is_active', 'order')
    list_filter = ('is_active',)
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}

class CourseInstructorInline(admin.TabularInline):
    model = CourseInstructor
    extra = 0

@admin.action(description='Aprobar y publicar cursos seleccionados')
def approve_publish(modeladmin, request, queryset):
    now = timezone.now()
    queryset.update(status=Course.Status.PUBLISHED, approved_by=request.user, approved_at=now, published_at=now)

@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'price', 'discount_enabled', 'currency', 'status', 'created_by', 'updated_at')
    list_filter = ('status', 'category', 'discount_enabled', 'discount_type', 'access_type', 'post_certificate_policy')
    search_fields = ('title', 'description', 'created_by__email')
    actions = [approve_publish]
    inlines = [CourseInstructorInline]
    readonly_fields = ('approved_by', 'approved_at', 'published_at', 'created_at', 'updated_at')

class LessonInline(admin.TabularInline):
    model = Lesson
    extra = 0

@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ('title', 'course', 'order', 'requires_quiz_to_unlock_next')
    list_filter = ('course',)
    inlines = [LessonInline]

@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ('title', 'module', 'order', 'video_provider', 'is_preview')
    list_filter = ('video_provider', 'is_preview', 'module__course')
    search_fields = ('title', 'module__course__title')

admin.site.register(CourseInstructor)
