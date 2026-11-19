#!/usr/bin/env bash
# Copy an already-built release from one environment's registry to another's, by digest, without
# rebuilding: the image that ran in staging is byte-for-byte the one that runs in production.
#   deploy/scripts/promote.sh staging production v1.4.0
# The caller's identity needs AcrPull on the source registry and AcrPush on the target.
source "$(dirname "$0")/lib.sh"
[[ $# -eq 3 ]] || { echo "usage: $(basename "$0") <from-env> <to-env> <tag>" >&2; exit 2; }
FROM_ENV="$1"; TO_ENV="$2"; TAG="$3"

ENV="$FROM_ENV"; tf_select_env; FROM_ACR="$(acr_server)"; FROM_ID="$(tf output -raw acr_id)"
ENV="$TO_ENV"; tf_select_env; TO_ACR="$(acr_server)"

log "importing $PROJECT-web:$TAG from $FROM_ACR into $TO_ACR"
az acr import --name "${TO_ACR%%.*}" --registry "$FROM_ID" \
  --source "$PROJECT-web:$TAG" --image "$PROJECT-web:$TAG" --force >/dev/null
log "promoted $TAG from $FROM_ENV to $TO_ENV"
