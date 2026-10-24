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
            'method': forms.Select(attrs={'data-payment-method-select': '1'}),
            'reference': forms.TextInput(attrs={'placeholder': 'Ej. TRX-000123, ID de PayPal o referencia del pago'}),
            'proof': forms.FileInput(attrs={'accept': '.pdf,.jpg,.jpeg,.png,.webp'}),
        }

    def __init__(self, *args, academy=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.academy = academy
        choices = []
        if academy and academy.payment_transfer_enabled:
            choices.append((Payment.Method.BANK, 'Transferencia bancaria'))
        if academy and academy.payment_paypal_enabled:
            choices.append((Payment.Method.PAYPAL, 'PayPal'))
        if academy and academy.payment_payphone_enabled:
            choices.append((Payment.Method.PAYPHONE, 'PayPhone'))
        if academy and academy.payment_card_enabled:
            choices.append((Payment.Method.CARD, 'Tarjeta · link solicitado por WhatsApp'))
        if academy and (academy.payment_link_1_enabled or academy.payment_link_2_enabled):
            choices.append((Payment.Method.PAYMENT_LINK, 'Link de pago'))
        if academy and academy.payment_whatsapp_enabled:
            choices.append((Payment.Method.WHATSAPP, 'Comprobante enviado por WhatsApp'))
        self.fields['method'].choices = choices or [(Payment.Method.BANK, 'Transferencia bancaria')]

    def clean_method(self):
        method = self.cleaned_data['method']
        allowed = {value for value, _label in self.fields['method'].choices}
        if method not in allowed:
            raise forms.ValidationError('Este método no está habilitado por la academia.')
        return method

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get('method')
        proof = cleaned.get('proof')
        existing_proof = bool(getattr(self.instance, 'proof', None))
        # En transferencias y proveedores externos el comprobante queda dentro del
        # sistema. En WhatsApp/tarjeta puede quedar respaldado en el chat.
        proof_expected = {
            Payment.Method.BANK, Payment.Method.PAYPAL,
            Payment.Method.PAYPHONE, Payment.Method.PAYMENT_LINK,
        }
        if method in proof_expected and not proof and not existing_proof:
            self.add_error('proof', 'Adjunta un comprobante legible para enviar el pago a revisión.')
        return cleaned
