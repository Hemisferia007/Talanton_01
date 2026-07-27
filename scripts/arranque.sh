#!/bin/sh
# Arranque del servicio web.
#
# Railway (y casi todo PaaS) inyecta el puerto por $PORT y espera que el
# proceso escuche ahí: fijarlo en 8000 hace que el health check nunca pase.
set -eu

PUERTO="${PORT:-8000}"

# Las migraciones van antes de aceptar tráfico. Si fallan, el deploy tiene que
# fallar acá y no dejar el servidor levantado contra un esquema viejo.
echo "[arranque] aplicando migraciones"
alembic upgrade head

echo "[arranque] escuchando en 0.0.0.0:${PUERTO}"
exec uvicorn talanton.web.app:app --host 0.0.0.0 --port "$PUERTO" --forwarded-allow-ips '*'
