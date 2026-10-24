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
    path('estudiantes/', views.student_courses, name='student_courses'),
    path('estudiantes/curso/<uuid:course_id>/', views.student_course_users, name='student_course_users'),
    path('usuarios/nuevo/', views.user_create, name='user_create'),
    path('usuarios/<uuid:user_id>/', views.user_detail, name='user_detail'),
    path('usuarios/<uuid:user_id>/accion/', views.user_action, name='user_action'),
    path('cursos/', views.courses, name='courses'),
    path('cursos/<uuid:course_id>/', views.course_detail, name='course_detail'),
    path('cursos/<uuid:course_id>/usuarios/<uuid:user_id>/accion/', views.course_user_action, name='course_user_action'),
    path('cursos/<uuid:course_id>/profesores/<uuid:user_id>/quitar/', views.course_professor_remove, name='course_professor_remove'),
    path('cursos/<uuid:course_id>/accion/', views.course_action, name='course_action'),
    path('cursos/<uuid:course_id>/pagos/<uuid:payment_id>/accion/', views.course_payment_action, name='course_payment_action'),
    path('cursos/<uuid:course_id>/accesos/nuevo/', views.course_enrollment_create, name='course_enrollment_create'),
    path('pagos/', views.payments, name='payments'),
    path('pagos/<uuid:payment_id>/accion/', views.payment_action, name='payment_action'),
    path('matriculas/', views.enrollments, name='enrollments'),
    path('matriculas/nueva/', views.enrollment_create, name='enrollment_create'),
    path('matriculas/<uuid:enrollment_id>/', views.enrollment_edit, name='enrollment_edit'),
    path('certificados/', views.certificates, name='certificates'),
    path('certificados/curso/<uuid:course_id>/', views.certificate_course_detail, name='certificate_course_detail'),
    path('certificados/estilo/', views.certificate_style, name='certificate_style'),
    path('certificados/estilo/vista-previa/', views.certificate_style_preview, name='certificate_style_preview'),
    path('categorias/', views.categories, name='categories'),
    path('categorias/nueva/', views.category_create, name='category_create'),
    path('bancos/', views.banks, name='banks'),
    path('bancos/nuevo/', views.bank_create, name='bank_create'),
    path('bancos/<int:bank_id>/editar/', views.bank_edit, name='bank_edit'),
    path('bancos/<int:bank_id>/visibilidad/', views.bank_toggle, name='bank_toggle'),
    path('auditoria/', views.audit, name='audit'),
    path('perfil/', views.owner_profile, name='owner_profile'),
    path('personalizacion/', views.branding, name='branding'),
    path('correo-smtp/', views.smtp_settings, name='smtp_settings'),
]
