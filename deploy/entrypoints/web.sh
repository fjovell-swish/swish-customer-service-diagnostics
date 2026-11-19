#!/usr/bin/env sh
# The diagnostics page: gunicorn. Override any value with the container's environment; any
# arguments run instead of gunicorn (`docker run ... python manage.py migrate`: the migrate job
# does exactly that before every rollout, so replicas never race to migrate).
set -eu

: "${DJANGO_SETTINGS_MODULE:=config.settings.production}"
: "${LOG_LEVEL:=INFO}"
: "${LOG_FORMAT:=json}"
: "${PORT:=8000}"
: "${GUNICORN_WORKERS:=2}"
: "${GUNICORN_THREADS:=8}"
export DJANGO_SETTINGS_MODULE LOG_LEVEL LOG_FORMAT PORT

cd /app
if [ "$#" -gt 0 ]; then
  exec "$@"
fi
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT}" \
  --worker-class gthread --workers "${GUNICORN_WORKERS}" --threads "${GUNICORN_THREADS}" \
  --access-logfile -
