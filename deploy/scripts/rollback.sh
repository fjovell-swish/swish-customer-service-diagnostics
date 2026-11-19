#!/usr/bin/env bash
# Roll the app back to a previously pushed tag.
#   deploy/scripts/rollback.sh production v1.3.2
source "$(dirname "$0")/lib.sh"
env_name "$@"; tf_select_env
TAG="${2:?tag to roll back to}"
log "rolling $ENV back to $TAG"
tf apply -auto-approve -var-file="$TFVARS" -var "image_tag=$TAG"
"$ROOT/deploy/scripts/health.sh" "$ENV"
