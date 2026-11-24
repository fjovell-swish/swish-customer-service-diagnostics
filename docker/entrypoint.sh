#!/usr/bin/env sh
# The image's entrypoint. The first argument picks the role; the rest is passed on:
#
#   entrypoint.sh [web]              the app and the MCP API on $PORT (the default, the Container
#                                    App): gunicorn with uvicorn workers (ASGI, config/asgi.py)
#   entrypoint.sh migrate [args...]  manage.py migrate --noinput (the migrate job, before each rollout,
#                                    so replicas never race to migrate)
#   entrypoint.sh manage <args...>   any manage.py command, e.g. `manage check --deploy`
#
# Override any default below with the container's environment.
set -eu

: "${DJANGO_SETTINGS_MODULE:=config.settings.production}"
: "${LOG_LEVEL:=INFO}"
: "${LOG_FORMAT:=json}"
: "${PORT:=8000}"
: "${GUNICORN_WORKERS:=2}"
export DJANGO_SETTINGS_MODULE LOG_LEVEL LOG_FORMAT PORT

cd /app

ROLE="${1:-web}"
[ "$#" -gt 0 ] && shift

case "$ROLE" in
  web)
    exec gunicorn config.asgi:application \
      --bind "0.0.0.0:${PORT}" \
      --worker-class uvicorn_worker.UvicornWorker --workers "${GUNICORN_WORKERS}" \
      --access-logfile - "$@"
    ;;
  migrate)
    exec python manage.py migrate --noinput "$@"
    ;;
  manage)
    exec python manage.py "$@"
    ;;
  *)
    echo "unknown role '$ROLE': expected web, migrate or manage <command>" >&2
    exit 2
    ;;
esac
