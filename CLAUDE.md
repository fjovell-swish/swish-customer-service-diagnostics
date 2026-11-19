# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Git rules (strict)

**Never push, commit, or merge directly to `main`.** Work on a feature branch
(`feature/<TICKET>/<short-description>`), push it, and open a pull request against `main`. Opening the
PR is where your work stops; humans review and merge.

## Overview

Django 6.1 page for customer support: diagnose "the charger doesn't work" from api-ocpp's database
(all tenant schemas, read-only). Python 3.15, pip-tools lockfiles (`requirements.txt`, `test-requirements.txt`). See README.md for the checks.

## Coding rules (all Swish repos)

- **Match the code around you**, **keep it simple**, **be precise**, **readable by the next person**,
  **verify, don't assume** (full version: `swish-charge/claude-code-setup/CLAUDE.md`).
- Full type hints (`mypy --strict`), one import per line, `pre-commit` (black, isort, flake8, djade, ...).
- Logging with %-style args, never f-strings. No magic numbers (`http.HTTPStatus` for status codes).
- Don't swallow exceptions: let errors raise so Sentry sees them.
- Tests: plain functions grouped by name prefix (`test_connectors_*`, `test_transactions_*`), fixtures over constants.

## Things that are easy to get wrong

- `services/ocpp/models.py` is **generated** by `manage.py regenerate_ocpp_models` (inspectdb on a live api-ocpp
  schema). Never edit it by hand; change the command (e.g. `MODEL_NAMES`) and regenerate.
- api-ocpp models are `managed = False` and the router refuses to migrate them. Never write to api-ocpp.
- Every api-ocpp query picks its tenant with `.using(ocpp_alias(tenant))`; the router's default is only a fallback.
- Checks in `diagnostics/checks.py` are pure functions over a `Snapshot`: no queries there. Data loading
  belongs in `diagnostics/snapshot.py`.
- Field values (statuses, error codes, rejection kinds) are the values api-ocpp stores; check its enums before adding one.

## Settings

`config/settings/{base,local,ci,production}.py`. `manage.py` and pytest default to `local` (SQLite,
no environment needed); CI's Postgres job uses `ci`; deployed containers use `production` (every
value from the environment). Sign-in in deployed environments is the auth proxy (`config/auth_proxy.py`).

## Commands

```bash
pip install -r test-requirements.txt               # Python 3.15
python manage.py runserver
python -m pytest -n 4                              # SQLite
DJANGO_SETTINGS_MODULE=config.settings.ci python -m pytest -n 4 --cov   # Postgres (docker compose up -d postgres), 100% coverage
mypy                                               # strict
pre-commit run --all-files
scripts/compile-requirements.sh                    # after changing pyproject.toml dependencies
python manage.py regenerate_ocpp_models            # needs OCPP_DATABASE_URL to a reachable api-ocpp
```

Coverage must stay at 100% (covdefaults). Deployment: `deploy/` (Terraform + scripts, see README).
