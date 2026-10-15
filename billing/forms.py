from django import forms
from .models import Payment

class PaymentProofForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ['method', 'reference', 'proof']

    def clean_method(self):
        method = self.cleaned_data['method']
        if method not in {Payment.Method.BANK, Payment.Method.WHATSAPP}:
            raise forms.ValidationError('Método no disponible en esta etapa.')
        return method
