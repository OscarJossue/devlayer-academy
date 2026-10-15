# Devlayer Academy

Base funcional de Devlayer Academy con **Django + PostgreSQL + Docker** y frontend propio en HTML/CSS/JS.

Esta versión elimina por completo Mailpit y cualquier bandeja SMTP local. El sistema de correo está preparado exclusivamente para **enviar correos mediante un servidor SMTP real externo**.

## Arranque local

Con Docker Desktop iniciado, abre PowerShell dentro de la carpeta del proyecto y ejecuta:

```bash
docker compose up --build
```

Servicios locales:

- Academia: http://localhost:8000
- Administración: http://localhost:8000/admin/
- Health check: http://localhost:8000/health/

El superadministrador inicial se toma de `.env`:

```text
DJANGO_SUPERUSER_EMAIL
DJANGO_SUPERUSER_PASSWORD
```

## PostgreSQL y el error de contraseña

Las versiones anteriores podían reutilizar un volumen de PostgreSQL creado con otra contraseña. PostgreSQL conserva la contraseña con la que se inicializó el volumen, aunque luego cambies `POSTGRES_PASSWORD` en `.env`.

Esta versión usa un volumen Docker con nombre estable:

```text
devlayer_academy_pgdata
```

Así se evita reutilizar accidentalmente el volumen anterior `devlayer_academy_postgres_data`.

Si en algún momento necesitas borrar completamente la base LOCAL de desarrollo y comenzar desde cero:

```bash
docker compose down -v
docker compose up --build
```

**No uses `down -v` en producción ni si necesitas conservar datos.**

## SMTP real de salida

No hay Mailpit, no hay puerto 8025 y no hay bandeja de entrada dentro del proyecto.

Devlayer Academy utiliza únicamente el SMTP que configures en `.env` para enviar:

- verificación de cuenta;
- recuperación de contraseña;
- aprobación o rechazo de pagos;
- disponibilidad de certificados;
- futuras notificaciones transaccionales.

Configura estas variables:

```env
EMAIL_HOST=smtp.tuproveedor.com
EMAIL_PORT=587
EMAIL_HOST_USER=academy@tudominio.com
EMAIL_HOST_PASSWORD=TU_CLAVE_SMTP
EMAIL_USE_TLS=1
EMAIL_USE_SSL=0
EMAIL_TIMEOUT=20
DEFAULT_FROM_EMAIL=academy@tudominio.com
```

Para SMTP por puerto **587 / STARTTLS**:

```env
EMAIL_USE_TLS=1
EMAIL_USE_SSL=0
```

Para SMTP por puerto **465 / SSL**:

```env
EMAIL_USE_TLS=0
EMAIL_USE_SSL=1
```

Nunca actives TLS y SSL al mismo tiempo.

Si una contraseña SMTP contiene caracteres especiales, colócala entre comillas simples dentro de `.env`, por ejemplo:

```env
EMAIL_HOST_PASSWORD='mi$clave#smtp'
```

## Probar el SMTP

Después de colocar tus credenciales y levantar Docker:

```bash
docker compose exec web python manage.py test_smtp tucorreo@dominio.com
```

Si funciona, verás:

```text
Correo SMTP enviado correctamente a tucorreo@dominio.com.
```

Si host, puerto, contraseña o TLS/SSL están mal, el comando devuelve el error real del servidor SMTP.

## `.env`

El ZIP incluye directamente `.env`, no `.env.example`.

El archivo contiene las claves locales de Django, PostgreSQL y cifrado. La sección SMTP queda vacía hasta que coloques tus credenciales reales.

**No publiques `.env` en GitHub.**

## Frontend

La interfaz pública y los paneles de estudiante/profesor usan frontend propio. No dependen de Bootstrap ni Tailwind.

Sistema visual global:

```text
static/css/design-system.css
```

Desde `:root` puedes modificar globalmente:

- tipografías;
- colores de marca;
- fondos;
- radios;
- sombras;
- altura, radio, padding y tipografía de botones.

Composición general:

```text
static/css/app.css
```

JavaScript:

```text
static/js/app.js
```

## Incluido

- Usuarios por correo y roles Estudiante / Profesor / Admin / Superadmin.
- Verificación de correo mediante SMTP real.
- Recuperación de contraseña mediante SMTP real.
- Categorías y cursos.
- Portadas de curso.
- Módulos y clases.
- Referencia de video cifrada en PostgreSQL.
- PDFs privados servidos mediante autorización.
- Matrículas independientes por curso.
- Vigencia, bloqueo y política posterior al certificado.
- Progreso secuencial.
- Cuestionarios por módulo y examen final.
- Preguntas aleatorias e intentos configurables.
- Importación CSV/XLSX.
- Excepciones de intentos por estudiante.
- Órdenes, comprobantes y aprobación de pagos.
- Pago aprobado -> matrícula activada automáticamente.
- Correos automáticos.
- Certificados PDF con QR y código de validación.
- Panel académico para profesor.
- Django Admin para Superadmin.
- Auditoría preparada en `audit`.

## Producción

Antes de desplegar al VPS:

1. `DJANGO_DEBUG=0`.
2. Configura el dominio real en `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` y `PUBLIC_BASE_URL`.
3. Configura SMTP real.
4. Cambia credenciales de desarrollo.
5. Conserva una copia segura de `CONTENT_ENCRYPTION_KEY`.
6. Usa Nginx + HTTPS.
7. Desactiva `AUTO_MAKEMIGRATIONS` y usa migraciones versionadas.
8. Ejecuta `python manage.py check --deploy`.

## Nota sobre video

La versión económica admite YouTube embebido. La referencia se almacena cifrada y solo se entrega desde una clase autorizada, pero YouTube no ofrece el mismo aislamiento que un servicio de streaming privado con URLs firmadas. La arquitectura deja preparado `video_provider` para migrarlo posteriormente.
