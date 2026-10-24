from django.urls import path
from . import views

app_name = 'catalog'

urlpatterns = [
    path('', views.course_list, name='course_list'),
    path('portada/<uuid:pk>/', views.course_thumbnail, name='course_thumbnail'),
    path('profesor/', views.professor_dashboard, name='professor_dashboard'),
    path('profesor/cursos/', views.professor_courses, name='professor_courses'),
    path('profesor/categorias/', views.professor_categories, name='professor_categories'),
    path('profesor/estudiantes/', views.professor_students_overview, name='professor_students_overview'),
    path('profesor/pagos/<uuid:payment_id>/comprobante/', views.professor_payment_proof, name='professor_payment_proof'),
    path('profesor/pagos/<uuid:payment_id>/accion/', views.professor_payment_action, name='professor_payment_action'),
    path('profesor/nuevo/', views.course_create, name='professor_course_create'),
    path('profesor/<uuid:pk>/editar/', views.course_edit, name='professor_course_edit'),
    path('profesor/<uuid:pk>/vista-estudiante/', views.professor_student_preview, name='professor_student_preview'),
    path('profesor/<uuid:pk>/vista-estudiante/clase/<uuid:lesson_id>/', views.professor_student_preview_lesson, name='professor_student_preview_lesson'),
    path('profesor/<uuid:pk>/vista-estudiante/cuestionario/<uuid:quiz_id>/', views.professor_student_preview_quiz, name='professor_student_preview_quiz'),
    path('profesor/<uuid:pk>/vista-estudiante/clase-magistral/', views.professor_student_preview_masterclass, name='professor_student_preview_masterclass'),
    path('profesor/<uuid:pk>/vista-estudiante/clase/<uuid:lesson_id>/video-seguro/<str:token>/', views.professor_student_preview_video, name='professor_student_preview_video'),
    path('profesor/<uuid:pk>/vista-estudiante/clase/<uuid:lesson_id>/material/pagina/<int:page_number>/', views.professor_student_preview_material, name='professor_student_preview_material'),
    path('profesor/<uuid:pk>/certificado/vista-previa/', views.certificate_preview, name='professor_certificate_preview'),
    path('profesor/<uuid:pk>/importar-contenido/', views.import_content, name='professor_import_content'),
    path('profesor/<uuid:pk>/estudiantes/', views.professor_students, name='professor_students'),
    path('profesor/<uuid:course_id>/estudiantes/<uuid:user_id>/habilitar/', views.professor_student_access_action, name='professor_student_access_action'),
    path('profesor/<uuid:pk>/revision/', views.submit_review, name='professor_submit_review'),
    path('profesor/<uuid:course_pk>/modulo/', views.module_create, name='professor_module_create'),
    path('profesor/modulo/<uuid:module_pk>/', views.module_editor, name='professor_module_editor'),
    path('profesor/modulo/<uuid:module_pk>/clase/', views.lesson_create, name='professor_lesson_create'),
    path('<slug:slug>/', views.course_detail, name='course_detail'),
]
