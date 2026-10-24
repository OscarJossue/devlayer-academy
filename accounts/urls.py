from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = 'accounts'
urlpatterns = [
    # No existe acceso global de academia. Estos nombres se conservan para compatibilidad
    # y muestran una pantalla que obliga a utilizar /academy/<slug>/.
    path('registro/', views.global_access_disabled, name='register'),
    path('ingresar/', views.global_access_disabled, name='login'),
    path('salir/', views.logout_view, name='logout'),
    path('verificacion/', views.verification_pending, name='verification_pending'),
    path('reenviar-verificacion/', views.resend_verification, name='resend_verification'),
    path('verificar/<str:token>/', views.global_access_disabled, name='verify_email'),
    path('recuperar/', views.global_access_disabled, name='password_reset'),
    path('recuperar/enviado/', views.global_access_disabled, name='password_reset_done'),
    path('recuperar/<uidb64>/<token>/', views.global_access_disabled, name='password_reset_confirm'),
    path('recuperar/listo/', views.global_access_disabled, name='password_reset_complete'),
]
