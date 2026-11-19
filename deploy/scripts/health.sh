#!/usr/bin/env bash
# Post-deploy checks: /healthz over the public FQDN, then Django's deployment checks and a read of
# api-ocpp inside the app.
#   deploy/scripts/health.sh dev
source "$(dirname "$0")/lib.sh"
env_name "$@"; tf_select_env
URL="$(tf output -raw web_url)/healthz"
for _ in $(seq 1 30); do
  if curl -fsS --max-time 5 "$URL" >/dev/null; then break; fi
  sleep 5
done
if ! curl -fsS --max-time 5 "$URL" >/dev/null; then
  echo "FAIL $URL" >&2
  exit 1
fi
log "ok  $URL"
log "running checks inside the app"
"$ROOT/deploy/scripts/manage.sh" "$ENV" check --deploy --database default
# Reads one api-ocpp table's definition: proves the read-only connection works.
"$ROOT/deploy/scripts/manage.sh" "$ENV" inspectdb --database ocpp_public charge_points_v16 >/dev/null
log "api-ocpp reachable"
