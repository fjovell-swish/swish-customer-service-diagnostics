#!/usr/bin/env bash
# Build the web image and push it to the environment's ACR.
#   deploy/scripts/build-push.sh dev [tag]
source "$(dirname "$0")/lib.sh"
env_name "$@"; tf_select_env
TAG="${2:-$(git_tag)}"
ACR="$(acr_server)"
log "logging in to $ACR"
az acr login --name "${ACR%%.*}" >/dev/null

log "building web ($TAG)"
docker build -f "$ROOT/docker/Dockerfile" \
  -t "$ACR/$PROJECT-web:$TAG" -t "$ACR/$PROJECT-web:latest" "$ROOT"
docker push "$ACR/$PROJECT-web:$TAG"
docker push "$ACR/$PROJECT-web:latest"
log "pushed $PROJECT-web:$TAG to $ACR"
echo "$TAG"
