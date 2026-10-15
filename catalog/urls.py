from django.urls import path
from . import views

app_name = 'catalog'

urlpatterns = [
    path('', views.course_list, name='course_list'),
    path('portada/<uuid:pk>/', views.course_thumbnail, name='course_thumbnail'),
    path('profesor/', views.professor_dashboard, name='professor_dashboard'),
    path('profesor/nuevo/', views.course_create, name='professor_course_create'),
    path('profesor/<uuid:pk>/editar/', views.course_edit, name='professor_course_edit'),
    path('profesor/<uuid:pk>/importar-contenido/', views.import_content, name='professor_import_content'),
    path('profesor/<uuid:pk>/estudiantes/', views.professor_students, name='professor_students'),
    path('profesor/<uuid:pk>/revision/', views.submit_review, name='professor_submit_review'),
    path('profesor/<uuid:course_pk>/modulo/', views.module_create, name='professor_module_create'),
    path('profesor/modulo/<uuid:module_pk>/clase/', views.lesson_create, name='professor_lesson_create'),
    path('<slug:slug>/', views.course_detail, name='course_detail'),
]
