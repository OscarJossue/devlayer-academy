from django.urls import path
from django.views.generic import RedirectView
from . import superadmin_views as views

app_name = 'superadmin'

urlpatterns = [
    # Compatibilidad con marcadores/enlaces del antiguo Django Admin.
    path('accounts/user/', RedirectView.as_view(pattern_name='superadmin:users', permanent=False)),
    path('catalog/course/', RedirectView.as_view(pattern_name='superadmin:courses', permanent=False)),
    path('billing/payment/', RedirectView.as_view(pattern_name='superadmin:payments', permanent=False)),
    path('learning/enrollment/', RedirectView.as_view(pattern_name='superadmin:enrollments', permanent=False)),
    path('certificates/certificate/', RedirectView.as_view(pattern_name='superadmin:certificates', permanent=False)),
    path('', views.dashboard, name='dashboard'),
    path('usuarios/', views.users, name='users'),
    path('usuarios/nuevo/', views.user_create, name='user_create'),
    path('usuarios/<uuid:user_id>/accion/', views.user_action, name='user_action'),
    path('cursos/', views.courses, name='courses'),
    path('cursos/<uuid:course_id>/accion/', views.course_action, name='course_action'),
    path('pagos/', views.payments, name='payments'),
    path('pagos/<uuid:payment_id>/accion/', views.payment_action, name='payment_action'),
    path('matriculas/', views.enrollments, name='enrollments'),
    path('matriculas/<uuid:enrollment_id>/', views.enrollment_edit, name='enrollment_edit'),
    path('certificados/', views.certificates, name='certificates'),
    path('categorias/', views.categories, name='categories'),
    path('categorias/nueva/', views.category_create, name='category_create'),
    path('bancos/', views.banks, name='banks'),
    path('bancos/nuevo/', views.bank_create, name='bank_create'),
    path('auditoria/', views.audit, name='audit'),
]
