from django.urls import path
from . import views

app_name = 'certificates'

urlpatterns = [
    path('mis-certificados/', views.my_certificates, name='my_certificates'),
    path('verificar/<str:code>/', views.verify, name='verify'),
    path('<str:code>/pdf/', views.certificate_pdf, name='pdf'),
]
