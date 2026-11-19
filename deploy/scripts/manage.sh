#!/usr/bin/env bash
# Run a manage.py command inside the web container of an environment.
#   deploy/scripts/manage.sh production check --deploy
#   deploy/scripts/manage.sh staging dbshell --database ocpp_public   # psql, read-only, on api-ocpp
source "$(dirname "$0")/lib.sh"
env_name "$@"; shift
CMD="python manage.py $*"
az containerapp exec -n "$(app)" -g "$RG" --command "$CMD"
