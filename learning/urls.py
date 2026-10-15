from django.urls import path
from . import views
app_name = 'learning'
urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('curso/<slug:course_slug>/', views.course_player, name='course_player'),
    path('curso/<slug:course_slug>/clase/<uuid:lesson_id>/', views.lesson_view, name='lesson'),
    path('curso/<slug:course_slug>/clase/<uuid:lesson_id>/completar/', views.complete_lesson, name='complete_lesson'),
    path('material/<str:token>/', views.protected_material, name='material'),
]
