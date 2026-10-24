import uuid
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator, FileExtensionValidator
from django.db import models
from catalog.models import Course, Module
from learning.models import Enrollment

class Quiz(models.Model):
    class Kind(models.TextChoices):
        MODULE = 'MODULE', 'Cuestionario de módulo'
        FINAL = 'FINAL', 'Examen final'

    class TimeMode(models.TextChoices):
        NONE = 'NONE', 'Sin tiempo'
        LIMIT = 'LIMIT', 'Tiempo límite'
        STOPWATCH = 'STOPWATCH', 'Cronómetro recomendado'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='quizzes')
    module = models.ForeignKey(Module, null=True, blank=True, on_delete=models.CASCADE, related_name='quizzes')
    title = models.CharField(max_length=180)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.MODULE)
    question_count = models.PositiveIntegerField(default=10)
    pass_percentage = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(100)])
    max_attempts = models.PositiveIntegerField(default=3, help_text='0 = intentos ilimitados')
    show_correct_answers = models.BooleanField(default=True, verbose_name='Mostrar respuestas correctas al finalizar')
    randomize_questions = models.BooleanField(default=True)
    randomize_choices = models.BooleanField(default=True)
    is_required = models.BooleanField(default=True)
    time_mode = models.CharField(max_length=20, choices=TimeMode.choices, default=TimeMode.NONE)
    time_limit_minutes = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(600)])
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['course', 'kind', 'title']

    @property
    def required_score(self):
        return self.pass_percentage or self.course.default_pass_percentage

    @property
    def timing_label(self):
        if self.time_mode == self.TimeMode.NONE:
            return 'Sin tiempo'
        minutes = self.time_limit_minutes or 0
        if self.time_mode == self.TimeMode.LIMIT:
            return f'{minutes} min · límite estricto'
        return f'{minutes} min · cronómetro recomendado'

    def clean(self):
        errors = {}
        if self.kind == self.Kind.MODULE:
            if not self.module_id:
                errors['module'] = 'Un cuestionario de módulo debe estar vinculado a un módulo.'
            elif self.course_id and self.module.course_id != self.course_id:
                errors['module'] = 'El módulo debe pertenecer al mismo curso de la evaluación.'
        elif self.kind == self.Kind.FINAL and self.module_id:
            errors['module'] = 'El examen final pertenece al curso completo y no a un módulo.'

        if self.time_mode != self.TimeMode.NONE and not self.time_limit_minutes:
            errors['time_limit_minutes'] = 'Indica los minutos para esta modalidad de tiempo.'

        if self.module_id and self.kind == self.Kind.MODULE:
            duplicate = Quiz.objects.filter(module_id=self.module_id, kind=self.Kind.MODULE).exclude(pk=self.pk)
            if duplicate.exists():
                errors['module'] = 'Este módulo ya tiene un cuestionario configurado.'
        if self.course_id and self.kind == self.Kind.FINAL:
            duplicate = Quiz.objects.filter(course_id=self.course_id, kind=self.Kind.FINAL).exclude(pk=self.pk)
            if duplicate.exists():
                errors['kind'] = 'Este curso ya tiene un examen final configurado.'

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.course} · {self.title}'

class Question(models.Model):
    class Type(models.TextChoices):
        SINGLE = 'SINGLE', 'Opción única'
        MULTIPLE = 'MULTIPLE', 'Selección múltiple'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='questions')
    text = models.TextField()
    question_type = models.CharField(max_length=20, choices=Type.choices, default=Type.SINGLE)
    explanation = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return self.text[:80]

class Choice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='choices')
    text = models.CharField(max_length=500)
    is_correct = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return self.text[:80]

class QuizAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quiz = models.ForeignKey(Quiz, on_delete=models.PROTECT, related_name='attempts')
    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name='quiz_attempts')
    number = models.PositiveIntegerField(default=1)
    question_ids = models.JSONField(default=list)
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    passed = models.BooleanField(default=False)
    identity_photo = models.ImageField(upload_to='private/exam_identity/%Y/%m/', null=True, blank=True)
    identity_consent = models.BooleanField(default=False)
    time_mode_snapshot = models.CharField(max_length=20, choices=Quiz.TimeMode.choices, default=Quiz.TimeMode.NONE)
    time_limit_minutes_snapshot = models.PositiveIntegerField(null=True, blank=True)
    elapsed_seconds = models.PositiveIntegerField(null=True, blank=True)
    overtime_seconds = models.PositiveIntegerField(default=0)
    timed_out = models.BooleanField(default=False)

    class Meta:
        ordering = ['-started_at']
        constraints = [models.UniqueConstraint(fields=['quiz', 'enrollment', 'number'], name='unique_quiz_attempt_number')]

    def clean(self):
        if self.quiz_id and self.enrollment_id and self.quiz.course_id != self.enrollment.course_id:
            raise ValidationError('El intento debe pertenecer al mismo curso de la matrícula.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.enrollment} · {self.quiz} · #{self.number}'

class AttemptAnswer(models.Model):
    attempt = models.ForeignKey(QuizAttempt, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(Question, on_delete=models.PROTECT)
    selected_choices = models.ManyToManyField(Choice, blank=True)
    is_correct = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['attempt', 'question'], name='unique_attempt_question_answer')]

class QuizEnrollmentOverride(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='enrollment_overrides')
    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name='quiz_overrides')
    max_attempts_override = models.PositiveIntegerField(null=True, blank=True, help_text='Vacío = usar regla del quiz. 0 = ilimitados.')
    extra_attempts = models.PositiveIntegerField(default=0)
    pass_percentage_override = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(100)])
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['quiz', 'enrollment'], name='unique_quiz_enrollment_override')]

    def __str__(self):
        return f'{self.enrollment} · {self.quiz}'
