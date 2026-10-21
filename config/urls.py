from django.urls import include, path

urlpatterns = [
    path('', include('tenancy.urls')),
    path('admin/', include('core.superadmin_urls')),
    path('', include('core.urls')),
    path('cuenta/', include('accounts.urls')),
    path('cursos/', include('catalog.urls')),
    path('academia/', include('learning.urls')),
    path('evaluaciones/', include('assessments.urls')),
    path('pagos/', include('billing.urls')),
    path('certificados/', include('certificates.urls')),
]
