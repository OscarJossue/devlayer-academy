from django.urls import path
from . import views

app_name = 'assessments'

urlpatterns = [
    path('<uuid:quiz_id>/', views.quiz_take, name='take'),
    path('resultado/<uuid:attempt_id>/', views.result, name='result'),
    path('profesor/curso/<uuid:course_id>/nueva/', views.quiz_create, name='professor_quiz_create'),
    path('profesor/<uuid:quiz_id>/importar/', views.import_questions_view, name='professor_import_questions'),
    path('profesor/intento/<uuid:attempt_id>/revisar/', views.review_attempt, name='professor_review_attempt'),
]
