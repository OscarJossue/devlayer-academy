from django.contrib.auth import views as auth_views
from django.urls import path

from accounts import views as account_views
from . import views

app_name = 'tenancy'

urlpatterns = [
    path('academy/<slug:slug>/', views.academy_public_home, name='academy_public'),
    path('academy/<slug:slug>/logo/', views.academy_logo, name='academy_logo'),
    path('academy/<slug:academy_slug>/ingresar/', account_views.AcademyLoginView.as_view(), name='academy_login'),
    path('academy/<slug:academy_slug>/registro/', account_views.register, name='academy_register'),
    path('academy/<slug:slug>/solicitud-pendiente/', views.membership_pending, name='membership_pending'),
    path('academy/<slug:academy_slug>/verificar/<str:token>/', account_views.verify_email, name='academy_verify_email'),
    path('academy/<slug:academy_slug>/recuperar/', account_views.AcademyPasswordResetView.as_view(), name='academy_password_reset'),
    path('academy/<slug:academy_slug>/recuperar/enviado/', account_views.password_reset_done, name='academy_password_reset_done'),
    path('academy/<slug:academy_slug>/recuperar/<uidb64>/<token>/', account_views.AcademyPasswordResetConfirmView.as_view(), name='academy_password_reset_confirm'),
    path('academy/<slug:academy_slug>/recuperar/listo/', account_views.password_reset_complete, name='academy_password_reset_complete'),
    path('academy/<slug:slug>/curso/<slug:course_slug>/', views.academy_public_course, name='academy_course_detail'),
    path('academy/<slug:slug>/portada/<uuid:pk>/', views.academy_course_thumbnail, name='academy_course_thumbnail'),

    path('sistema/ingresar/', views.SystemOwnerLoginView.as_view(), name='system_login'),
    path('sistema/salir/', auth_views.LogoutView.as_view(next_page='/sistema/ingresar/'), name='system_logout'),
    path('sistema/', views.system_dashboard, name='system_dashboard'),
    path('sistema/finanzas/', views.system_finances, name='system_finances'),
    path('sistema/planes/', views.plan_list, name='plan_list'),
    path('sistema/planes/nuevo/', views.plan_create, name='plan_create'),
    path('sistema/planes/<uuid:plan_id>/editar/', views.plan_edit, name='plan_edit'),
    path('sistema/academias/', views.academy_list, name='academy_list'),
    path('sistema/academias/nueva/', views.academy_create, name='academy_create'),
    path('sistema/academias/<uuid:academy_id>/', views.academy_detail, name='academy_detail'),
    path('sistema/academias/<uuid:academy_id>/actualizar/', views.academy_update, name='academy_update'),
    path('sistema/academias/<uuid:academy_id>/licencia/', views.license_update, name='license_update'),
    path('sistema/academias/<uuid:academy_id>/licencia/accion/', views.license_action, name='license_action'),
    path('sistema/academias/<uuid:academy_id>/superadmin/nuevo/', views.academy_superadmin_create, name='academy_superadmin_create'),
    path('licencia-bloqueada/', views.license_blocked, name='license_blocked'),
]
