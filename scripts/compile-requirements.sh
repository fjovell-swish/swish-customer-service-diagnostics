#!/usr/bin/env bash
# Regenerate the hashed lockfiles from pyproject.toml. Run after changing dependencies; commit both.
set -euo pipefail
cd "$(dirname "$0")/.."
pip-compile --generate-hashes --strip-extras --allow-unsafe --output-file=requirements.txt pyproject.toml "$@"
pip-compile --generate-hashes --strip-extras --allow-unsafe --extra=test --output-file=test-requirements.txt pyproject.toml "$@"
