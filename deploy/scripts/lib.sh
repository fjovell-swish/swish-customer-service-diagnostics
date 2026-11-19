#!/usr/bin/env bash
# Shared helpers for deploy/scripts/*. Source it; do not run it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TF_DIR="$ROOT/deploy/terraform"
PROJECT="${PROJECT:-swishdiag}"

usage_env() { echo "usage: $(basename "$0") <dev|staging|production> ${1:-}" >&2; exit 2; }

# RG is for the scripts that source this file (logs.sh, manage.sh).
# shellcheck disable=SC2034
env_name() { [[ $# -ge 1 ]] || usage_env; ENV="$1"; RG="rg-${PROJECT}-${ENV}"; }

tf() { terraform -chdir="$TF_DIR" "$@"; }

tf_select_env() {
  # one Terraform workspace per environment; tfvars file per environment next to the code
  tf workspace select -or-create "$ENV" >/dev/null
  TFVARS="$TF_DIR/$ENV.tfvars"
  [[ -f "$TFVARS" ]] || { echo "missing $TFVARS (copy terraform.tfvars.example)" >&2; exit 2; }
}

acr_server() { tf output -raw acr_login_server; }

git_tag() { git -C "$ROOT" rev-parse --short HEAD; }

app() { echo "ca-${PROJECT}-${ENV}-web"; }

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
