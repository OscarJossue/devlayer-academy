#!/bin/sh
set -eu

python - <<'PY'
import os
import time
import psycopg

cfg = {
    'host': os.getenv('POSTGRES_HOST', 'db'),
    'port': int(os.getenv('POSTGRES_PORT', '5432')),
    'dbname': os.getenv('POSTGRES_DB', 'devlayer'),
    'user': os.getenv('POSTGRES_USER', 'devlayer'),
    'password': os.getenv('POSTGRES_PASSWORD', ''),
    'connect_timeout': 3,
}

last_error = None
for attempt in range(1, 31):
    try:
        with psycopg.connect(**cfg):
            print('PostgreSQL listo y autenticación correcta.')
        break
    except psycopg.OperationalError as exc:
        last_error = exc
        text = str(exc).lower()
        if 'password authentication failed' in text:
            print('\nERROR: PostgreSQL rechazó la contraseña configurada.')
            print('Si cambiaste POSTGRES_PASSWORD con un volumen antiguo y no necesitas conservarlo:')
            print('  docker compose down -v')
            print('  docker compose up --build')
            raise SystemExit(12)
        if attempt == 30:
            raise
        print(f'Esperando PostgreSQL... intento {attempt}/30')
        time.sleep(2)
else:
    raise last_error
PY

# Tenancy lleva migraciones versionadas. Las apps legadas conservan su 0001 inicial automático.
python manage.py makemigrations accounts catalog learning assessments billing certificates audit --noinput
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py create_initial_superadmin

# En instalaciones nuevas no se crean cursos, academias ni usuarios de ejemplo.
if [ "${ENABLE_DEMO_DATA:-0}" = "1" ]; then
  python manage.py seed_demo
fi

# La migración de la academia antigua es opt-in. Una base limpia permanece vacía.
if [ "${MIGRATE_LEGACY_TENANCY:-0}" = "1" ]; then
  python manage.py bootstrap_tenancy --force
fi

python manage.py check
exec "$@"
