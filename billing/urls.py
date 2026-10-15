from django.urls import path
from . import views

app_name = 'billing'

urlpatterns = [
    path('historial/', views.history, name='history'),
    path('curso/<slug:course_slug>/', views.checkout, name='checkout'),
    path('orden/<uuid:order_id>/', views.order_detail, name='order'),
    path('comprobante/<uuid:payment_id>/', views.payment_proof, name='payment_proof'),
]
