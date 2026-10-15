import uuid
from django.core.validators import MinValueValidator, MaxValueValidator, FileExtensionValidator
from django.db import models
from catalog.models import Course, Module
from learning.models import Enrollment

class Quiz(models.Model):
    class Kind(models.TextChoices):
        MODULE = 'MODULE', 'Cuestionario de módulo'
        FINAL = 'FINAL', 'Examen final'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='quizzes')
    module = models.ForeignKey(Module, null=True, blank=True, on_delete=models.CASCADE, related_name='quizzes')
    title = models.CharField(max_length=180)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.MODULE)
    question_count = models.PositiveIntegerField(default=10)
    pass_percentage = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(100)])
    max_attempts = models.PositiveIntegerField(default=3, help_text='0 = intentos ilimitados')
    randomize_questions = models.BooleanField(default=True)
    randomize_choices = models.BooleanField(default=True)
    is_required = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['course', 'kind', 'title']

    @property
    def required_score(self):
        return self.pass_percentage or self.course.default_pass_percentage

    def __str__(self):
        return f'{self.course} · {self.title}'

class Question(models.Model):
    class Type(models.TextChoices):
        SINGLE = 'SINGLE', 'Opción única'
        MULTIPLE = 'MULTIPLE', 'Selección múltiple'
        TRUE_FALSE = 'TRUE_FALSE', 'Verdadero / Falso'

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

    class Meta:
        ordering = ['-started_at']
        constraints = [models.UniqueConstraint(fields=['quiz', 'enrollment', 'number'], name='unique_quiz_attempt_number')]

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
