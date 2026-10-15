import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


def _fernet():
    raw = getattr(settings, 'CONTENT_ENCRYPTION_KEY', '') or ''
    if raw:
        key = raw.encode()
    else:
        digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


class EncryptedTextField(models.TextField):
    prefix = 'enc::'

    def from_db_value(self, value, expression, connection):
        return self.to_python(value)

    def to_python(self, value):
        if value is None or value == '':
            return value
        if isinstance(value, str) and value.startswith(self.prefix):
            token = value[len(self.prefix):].encode()
            try:
                return _fernet().decrypt(token).decode()
            except InvalidToken:
                return ''
        return value

    def get_prep_value(self, value):
        if value is None or value == '':
            return value
        value = str(value)
        if value.startswith(self.prefix):
            return value
        token = _fernet().encrypt(value.encode()).decode()
        return self.prefix + token
