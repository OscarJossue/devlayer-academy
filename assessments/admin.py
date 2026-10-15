from django.contrib import admin
from .models import Quiz, Question, Choice, QuizAttempt, AttemptAnswer, QuizEnrollmentOverride

# Etiquetas del panel en español.
for _model, _singular, _plural in [
    (Quiz, 'evaluación', 'evaluaciones'), (Question, 'pregunta', 'preguntas'),
    (Choice, 'opción', 'opciones'), (QuizAttempt, 'intento', 'intentos'),
    (AttemptAnswer, 'respuesta de intento', 'respuestas de intentos'),
    (QuizEnrollmentOverride, 'excepción de evaluación', 'excepciones de evaluación'),
]:
    _model._meta.verbose_name = _singular
    _model._meta.verbose_name_plural = _plural

for _model, _labels in {
    Quiz: {'course':'curso','module':'módulo','title':'nombre','kind':'tipo','question_count':'preguntas por intento','pass_percentage':'nota mínima (%)','max_attempts':'intentos máximos','randomize_questions':'preguntas aleatorias','randomize_choices':'respuestas aleatorias','is_required':'obligatoria','is_active':'activa'},
    Question: {'quiz':'evaluación','text':'pregunta','question_type':'tipo','explanation':'explicación','is_active':'activa','order':'orden'},
    Choice: {'question':'pregunta','text':'respuesta','is_correct':'correcta','order':'orden'},
    QuizAttempt: {'quiz':'evaluación','enrollment':'matrícula','number':'número de intento','score':'nota','passed':'aprobado','identity_photo':'foto de identidad','identity_consent':'consentimiento'},
    QuizEnrollmentOverride: {'quiz':'evaluación','enrollment':'matrícula','max_attempts_override':'intentos máximos especiales','extra_attempts':'intentos adicionales','pass_percentage_override':'nota mínima especial','notes':'notas'},
}.items():
    for _field, _label in _labels.items():
        _model._meta.get_field(_field).verbose_name = _label

class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 4

@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ('title', 'course', 'kind', 'question_count', 'pass_percentage', 'max_attempts', 'is_required', 'is_active')
    list_filter = ('kind', 'is_required', 'is_active', 'course')

@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('text', 'quiz', 'question_type', 'is_active')
    list_filter = ('quiz__course', 'quiz', 'question_type')
    inlines = [ChoiceInline]

@admin.register(QuizAttempt)
class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = ('enrollment', 'quiz', 'number', 'score', 'passed', 'submitted_at')
    list_filter = ('passed', 'quiz__course', 'quiz')

admin.site.register(Choice)
admin.site.register(AttemptAnswer)

@admin.register(QuizEnrollmentOverride)
class QuizEnrollmentOverrideAdmin(admin.ModelAdmin):
    list_display = ('quiz', 'enrollment', 'max_attempts_override', 'extra_attempts', 'pass_percentage_override')
    list_filter = ('quiz__course', 'quiz')
    search_fields = ('enrollment__user__email', 'quiz__title')
