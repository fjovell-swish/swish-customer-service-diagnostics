#!/usr/bin/env bash
# First-time creation of an environment: registry, image, infrastructure.
# Needs TF_VAR_ocpp_database_url (a read-only user on api-ocpp's database), see deploy/terraform/README.md.
#   deploy/scripts/bootstrap.sh staging
source "$(dirname "$0")/lib.sh"
env_name "$@"; tf_select_env
tf init -input=false >/dev/null
log "creating registry"
tf apply -auto-approve -var-file="$TFVARS" -target=azurerm_container_registry.acr
TAG="$("$ROOT/deploy/scripts/build-push.sh" "$ENV" | tail -1)"
log "creating everything else"
tf apply -auto-approve -var-file="$TFVARS" -var "image_tag=$TAG"
"$ROOT/deploy/scripts/migrate.sh" "$ENV"
log "allow these in api-ocpp's Postgres firewall: $(tf output -json outbound_ip_addresses)"
"$ROOT/deploy/scripts/health.sh" "$ENV"
log "web: $(tf output -raw web_url)"
log "give the auth proxy the secret from: terraform output -raw proxy_secret"
