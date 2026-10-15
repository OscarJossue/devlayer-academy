# Seguridad · Devlayer Academy

- No publiques `.env`.
- Cambia todas las credenciales de desarrollo.
- Mantén `DJANGO_SECRET_KEY` y `CONTENT_ENCRYPTION_KEY` fuera del repositorio.
- Usa HTTPS en producción.
- Los PDFs se sirven mediante vistas autenticadas; no publiques el volumen `media` directamente con Nginx.
- No configures una regla Nginx genérica para `/_private-media/`.
- YouTube no listado no equivale a DRM.
- Las fotografías opcionales de examen deben tener política de consentimiento, acceso y retención.
- Los datos financieros deben permanecer restringidos a superadministradores.
- Antes de producción ejecuta `python manage.py check --deploy` dentro del contenedor.
