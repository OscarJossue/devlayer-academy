from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import BankAccount, Order, Payment
from .services import approve_payment

# Etiquetas del panel en español.
BankAccount._meta.verbose_name = 'cuenta bancaria'
BankAccount._meta.verbose_name_plural = 'cuentas bancarias'
Order._meta.verbose_name = 'orden de pago'
Order._meta.verbose_name_plural = 'órdenes de pago'
Payment._meta.verbose_name = 'pago'
Payment._meta.verbose_name_plural = 'pagos'

for _model, _labels in {
    BankAccount: {'bank_name':'banco','account_type':'tipo de cuenta','account_number':'número de cuenta','holder_name':'titular','holder_id':'identificación del titular','instructions':'instrucciones','is_active':'activa','order':'orden'},
    Order: {'code':'código','user':'estudiante','course':'curso','amount':'monto','currency':'moneda','status':'estado','created_at':'creada','updated_at':'actualizada'},
    Payment: {'order':'orden','method':'método','amount':'monto','reference':'referencia','proof':'comprobante','status':'estado','notes':'notas','approved_by':'aprobado por','approved_at':'fecha de aprobación','created_at':'creado','updated_at':'actualizado'},
}.items():
    for _field, _label in _labels.items():
        _model._meta.get_field(_field).verbose_name = _label

class SuperadminFinanceMixin:
    def has_module_permission(self, request):
        return bool(request.user and request.user.is_superuser)
    def has_view_permission(self, request, obj=None):
        return bool(request.user and request.user.is_superuser)
    def has_add_permission(self, request):
        return bool(request.user and request.user.is_superuser)
    def has_change_permission(self, request, obj=None):
        return bool(request.user and request.user.is_superuser)
    def has_delete_permission(self, request, obj=None):
        return bool(request.user and request.user.is_superuser)

@admin.action(description='Aprobar pagos y activar curso automáticamente')
def approve_selected(modeladmin, request, queryset):
    for payment in queryset.select_related('order__user', 'order__course'):
        approve_payment(payment, request.user)

@admin.action(description='Rechazar pagos seleccionados')
def reject_selected(modeladmin, request, queryset):
    for payment in queryset:
        payment.status = Payment.Status.REJECTED
        payment.save(update_fields=['status', 'updated_at'])

@admin.register(BankAccount)
class BankAccountAdmin(SuperadminFinanceMixin, admin.ModelAdmin):
    list_display = ('bank_name', 'account_number', 'holder_name', 'is_active', 'order')

@admin.register(Order)
class OrderAdmin(SuperadminFinanceMixin, admin.ModelAdmin):
    list_display = ('code', 'user', 'course', 'amount', 'currency', 'status', 'created_at')
    list_filter = ('status', 'currency', 'course')
    search_fields = ('code', 'user__email', 'course__title')
    readonly_fields = ('code', 'created_at', 'updated_at')

@admin.register(Payment)
class PaymentAdmin(SuperadminFinanceMixin, admin.ModelAdmin):
    list_display = ('order', 'method', 'amount', 'status', 'reference', 'proof_link', 'created_at', 'approved_at')
    list_filter = ('status', 'method', 'order__course')
    search_fields = ('order__code', 'order__user__email', 'reference')
    actions = [approve_selected, reject_selected]
    readonly_fields = ('approved_at', 'created_at', 'updated_at', 'proof_link')

    @admin.display(description='Comprobante')
    def proof_link(self, obj):
        if not obj or not obj.proof:
            return '—'
        return format_html('<a href="{}" target="_blank">Ver comprobante</a>', reverse('billing:payment_proof', args=[obj.id]))
