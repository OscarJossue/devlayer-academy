from django.urls import path
from . import views

app_name = 'learning'
urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('curso/<slug:course_slug>/', views.course_player, name='course_player'),
    path('curso/<slug:course_slug>/completado/', views.completion, name='completion'),
    path('curso/<slug:course_slug>/clase-magistral/', views.masterclass, name='masterclass'),
    path('curso/<slug:course_slug>/clase/<uuid:lesson_id>/', views.lesson_view, name='lesson'),
    path('curso/<slug:course_slug>/clase/<uuid:lesson_id>/material/pagina/<int:page_number>/', views.material_page, name='material_page'),
    path('curso/<slug:course_slug>/clase/<uuid:lesson_id>/completar/', views.complete_lesson, name='complete_lesson'),
    # Se conserva la ruta solo para invalidar enlaces antiguos con 404.
    path('material/<str:token>/', views.protected_material, name='material'),
]
