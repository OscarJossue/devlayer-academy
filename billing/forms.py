from django import forms

from .models import Payment


class PaymentProofForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ['method', 'reference', 'proof']
        labels = {
            'method': 'Método utilizado',
            'reference': 'Referencia / número de comprobante',
            'proof': 'Comprobante',
        }
        widgets = {
            'reference': forms.TextInput(attrs={'placeholder': 'Ej. TRX-000123 o referencia bancaria'}),
            'proof': forms.FileInput(attrs={'accept': '.pdf,.jpg,.jpeg,.png,.webp'}),
        }

    def __init__(self, *args, academy=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.academy = academy
        choices = []
        if academy and academy.payment_transfer_enabled:
            choices.append((Payment.Method.BANK, 'Transferencia bancaria'))
        if academy and academy.payment_whatsapp_enabled:
            choices.append((Payment.Method.WHATSAPP, 'Reportado por WhatsApp'))
        self.fields['method'].choices = choices or [(Payment.Method.BANK, 'Transferencia bancaria')]

    def clean_method(self):
        method = self.cleaned_data['method']
        allowed = {value for value, _label in self.fields['method'].choices}
        if method not in allowed:
            raise forms.ValidationError('Este método no está habilitado por la academia.')
        return method
