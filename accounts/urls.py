from django.contrib.auth import views as auth_views
from django.urls import path
from .forms import EmailAuthenticationForm
from . import views

app_name = 'accounts'
urlpatterns = [
    path('registro/', views.register, name='register'),
    path('ingresar/', views.AcademyLoginView.as_view(authentication_form=EmailAuthenticationForm), name='login'),
    path('salir/', auth_views.LogoutView.as_view(), name='logout'),
    path('verificacion/', views.verification_pending, name='verification_pending'),
    path('reenviar-verificacion/', views.resend_verification, name='resend_verification'),
    path('verificar/<str:token>/', views.verify_email, name='verify_email'),
    path('recuperar/', views.AcademyPasswordResetView.as_view(template_name='registration/password_reset_form.html', email_template_name='registration/password_reset_email.txt', subject_template_name='registration/password_reset_subject.txt'), name='password_reset'),
    path('recuperar/enviado/', auth_views.PasswordResetDoneView.as_view(template_name='registration/password_reset_done.html'), name='password_reset_done'),
    path('recuperar/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='registration/password_reset_confirm.html'), name='password_reset_confirm'),
    path('recuperar/listo/', auth_views.PasswordResetCompleteView.as_view(template_name='registration/password_reset_complete.html'), name='password_reset_complete'),
]
