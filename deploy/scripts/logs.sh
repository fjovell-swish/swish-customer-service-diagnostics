#!/usr/bin/env bash
# Tail the app's logs.
#   deploy/scripts/logs.sh staging
#   deploy/scripts/logs.sh production --tail 500
source "$(dirname "$0")/lib.sh"
env_name "$@"; shift
az containerapp logs show -n "$(app)" -g "$RG" --type console --follow "$@"
