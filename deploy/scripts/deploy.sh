#!/usr/bin/env bash
# Full release: build+push (unless --tag given), migrate on the new image, roll the app, health check.
#   deploy/scripts/deploy.sh dev                       # build from HEAD and deploy
#   deploy/scripts/deploy.sh production --tag v1.4.0   # deploy an already-built tag
#   deploy/scripts/deploy.sh dev --plan                # terraform plan only
source "$(dirname "$0")/lib.sh"
env_name "$@"; shift; tf_select_env
TAG=""; PLAN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag) TAG="$2"; shift 2 ;;
    --plan) PLAN=1; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
[[ -n "$TAG" ]] || TAG="$("$ROOT/deploy/scripts/build-push.sh" "$ENV" | tail -1)"

if [[ $PLAN -eq 1 ]]; then
  tf plan -var-file="$TFVARS" -var "image_tag=$TAG"
  exit 0
fi

# Migrations first, on the NEW image, so the new code never runs against an old schema. They only
# touch this app's database: api-ocpp's models are never migrated (config/routers.py).
log "updating migrate job to $TAG"
tf apply -auto-approve -var-file="$TFVARS" -var "image_tag=$TAG" -target=azurerm_container_app_job.migrate
"$ROOT/deploy/scripts/migrate.sh" "$ENV"

log "rolling web to $TAG"
tf apply -auto-approve -var-file="$TFVARS" -var "image_tag=$TAG"

"$ROOT/deploy/scripts/health.sh" "$ENV"
log "deployed $TAG to $ENV"
