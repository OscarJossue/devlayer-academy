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
            print('Esto suele ocurrir cuando existe un volumen antiguo creado con otra contraseña.')
            print('Esta versión usa un volumen estable nuevo: devlayer_academy_pgdata.')
            print('Si ese volumen ya existía y NO necesitas conservar sus datos, ejecuta:')
            print('  docker compose down -v')
            print('y después:')
            print('  docker compose up --build')
            raise SystemExit(12)
        if attempt == 30:
            raise
        print(f'Esperando PostgreSQL... intento {attempt}/30')
        time.sleep(2)
else:
    raise last_error
PY

if [ "${AUTO_MAKEMIGRATIONS:-1}" = "1" ]; then
  python manage.py makemigrations accounts catalog learning assessments billing certificates audit --noinput
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py create_initial_superadmin

if [ "${SEED_DEMO:-0}" = "1" ]; then
  python manage.py seed_demo
fi

python manage.py check
exec "$@"
