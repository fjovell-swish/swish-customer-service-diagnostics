# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Git rules (strict)

**Never push, commit, or merge directly to `main`.** Work on a feature branch
(`feature/<TICKET>/<short-description>`), push it, and open a pull request against `main`. Opening the
PR is where your work stops; humans review and merge.

## Overview

Django 5.2 page for customer support: diagnose "the charger doesn't work" from api-ocpp's database
(all tenant schemas, read-only). Python 3.11, managed with `uv`. See README.md for the checks.

## Coding rules (all Swish repos)

- **Match the code around you**, **keep it simple**, **be precise**, **readable by the next person**,
  **verify, don't assume** (full version: `swish-charge/claude-code-setup/CLAUDE.md`).
- Full type hints, one import per line, `pre-commit` (ruff, reorder-python-imports).
- Logging with %-style args, never f-strings. No magic numbers (`http.HTTPStatus` for status codes).
- Don't swallow exceptions: let errors raise so Sentry sees them.
- Tests: plain functions grouped by name prefix (`test_connectors_*`, `test_transactions_*`), fixtures over constants.

## Things that are easy to get wrong

- `services/ocpp/models.py` is **copied** from fjovell-swish/swish-admin (generated there). Never edit it here.
- api-ocpp models are `managed = False` and the router refuses to migrate them. Never write to api-ocpp.
- Every api-ocpp query picks its tenant with `.using(ocpp_alias(tenant))`; the router's default is only a fallback.
- Checks in `diagnostics/checks.py` are pure functions over a `Snapshot`: no queries there. Data loading
  belongs in `diagnostics/snapshot.py`.
- Field values (statuses, error codes, rejection kinds) are the values api-ocpp stores; check its enums before adding one.

## Commands

```bash
uv sync
uv run python manage.py runserver
uv run pytest
uv run pre-commit run --all-files
```
