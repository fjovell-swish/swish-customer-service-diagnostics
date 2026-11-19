#!/usr/bin/env bash
# Run the migrate job for an environment and wait for it to finish.
#   deploy/scripts/migrate.sh staging
source "$(dirname "$0")/lib.sh"
env_name "$@"
JOB="caj-${PROJECT}-${ENV}-migrate"
log "starting $JOB"
EXEC=$(az containerapp job start -n "$JOB" -g "$RG" --query name -o tsv)
for _ in $(seq 1 120); do
  STATUS=$(az containerapp job execution show -n "$JOB" -g "$RG" --job-execution-name "$EXEC" --query properties.status -o tsv)
  case "$STATUS" in
    Succeeded) log "migrations applied"; exit 0 ;;
    Failed|Stopped) echo "migrate job $STATUS" >&2
      az containerapp job logs show -n "$JOB" -g "$RG" --execution "$EXEC" --container migrate 2>/dev/null | tail -50
      exit 1 ;;
  esac
  sleep 5
done
echo "timed out waiting for $JOB" >&2; exit 1
