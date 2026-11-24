# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Git rules

Commit and push straight to `main`; there are no feature branches or pull requests in this repo.
Pushing to `main` deploys nothing: it runs the CI workflows (tests, pre-commit, type check, image
build, Terraform) and, when `pyproject.toml` changed, recompiles the lockfiles and pushes a commit
on its own (pull before pushing again).

**Releasing is separate:** pushing a `vX.Y.Z` tag deploys to staging, then to production after an
approval (`.github/workflows/deploy.yaml`). Never push a tag unless asked to release.

Before every push, run locally: pre-commit, mypy and the tests, which run on **SQLite** (see
Commands). CI also runs them on Postgres, where
coverage must stay at 100%: a test that needs Postgres is marked `postgres` and skips locally.

## Overview

A guided workflow for customer support: when a customer says "the charger doesn't work", the rep
finds the charger (identity, name or serial, across every api-ocpp tenant) and starts a case; the
app asks only the questions that matter, then writes a diagnosis (likely cause, confidence, next
steps, customer reply, ticket summary). See README.md for the questions and rules.

It also replaces the former swish-admin: the `data` role browses every table of api-ocpp,
api-gateway and api-gireve in the admin (read-only) and sees the deployments page.

Python 3.15, Django 6.1, pip-tools lockfiles. It reads **api-ocpp's database, read-only**, one
connection alias per tenant schema (`ocpp_<tenant>`), and **api-gateway's and api-gireve's**, one
alias each (`gateway`, `gireve`; optional when deployed). It keeps its own data (cases, users) in
its own Postgres (`default`; SQLite locally).

CI is this repo's own workflows (`.github/workflows/`). They don't use the shared
`swish-charge/ci-workflows`: its reusable workflows are internal to the `swish-charge` organization,
and this repo lives under a personal account, so GitHub refuses to run them from here.

## Layout

- `diagnostics/snapshot.py`: every api-ocpp query. `find_chargers()` searches all tenants;
  `collect()` loads one charger's `Snapshot` (connectors, incidents, refused badges, sessions,
  maintenance, firmware) for the last 24 h.
- `diagnostics/checks.py`: the checks, **pure functions** over a `Snapshot` returning `Finding`s
  (severity, title, evidence, action, customer reply). Thresholds are named constants at the top.
  A new check is a function added to `CHECKS` plus its tests; no queries here.
- `diagnostics/workflow.py`: the workflow, **pure functions** over a `Situation` (snapshot,
  findings, answers): `QUESTIONS` (each returns a `Question` only when it's relevant),
  `next_question()`, `RULES` (first match wins) and `diagnose()`, which also writes the ticket
  summary. A new question: a function in `QUESTIONS`, its key in `QUESTION_ORDER`, and the rules
  that use it; a new rule: a function in `RULES` at the right place. Tests for each.
- `diagnostics/assistant.py`: Claude's assessment of a diagnosed case. `case_context()` turns a
  `Situation` into the JSON Claude gets (personal fields left out, badge numbers masked
  everywhere); `assess()` calls the Messages API with a forced tool (`ASSESSMENT_SCHEMA`) and
  returns an `Assessment`. The SDK talks over `httpx2`, not `httpx`, so respx doesn't see it: tests
  pass a client on an `httpx2.MockTransport`. `diagnostics/jira.py`: the escalation, a Jira
  issue from Claude's ticket draft (REST API v3, httpx).
- `diagnostics/models.py`: `Case` (the charger, the answers as JSON, the diagnosis as written).
  `diagnostics/admin.py`: the case history. `diagnostics/forms.py`: start and answer forms.
- `diagnostics/views.py` + `templates/diagnostics/`: `/` (find a charger, start a case, latest
  cases) and `/cases/<id>/` (next question or the diagnosis; Back, start over, diagnose again,
  close), on the admin's look.
- `services/<service>/models.py` (`ocpp`, `gateway`, `gireve`): the services' tables,
  **generated** (see below); `services/<service>/admin.py` registers them read-only through
  `services/admin_registration.py`.
- `services/ocpp/management/commands/regenerate_models.py`: the generator (inspectdb), for all
  three services. `seed_fake_data.py`: fake chargers in the local SQLite tenants, one per problem
  the workflow diagnoses (refuses anything but SQLite), and empty local gateway and gireve tables.
  A new rule or check is worth a fake charger there.
- `deployments/`: the deployments page. `registry.py` mirrors the
  services' `ci-cd.y*ml`; update it when they change.
- `config/settings/`: `base` (shared), `local` (default for `manage.py` and pytest; SQLite, no
  environment needed), `ci` (GitHub Actions' Postgres), `production` (default for wsgi; every value
  from the environment, the required ones listed at the top).
- `config/auth_proxy.py`: sign-in in deployed environments (below). `config/routers.py`: keeps
  the services' models off `default` and never migrates them. `config/tenancy.py`: the admin's
  tenant switcher.
- `deploy/`: the image (`web.Dockerfile`; `entrypoints/entrypoint.sh` runs the role it's given:
  `web`, `migrate` or `manage <command>`), Terraform for Azure Container Apps (VNet, app, migrate
  job, private Postgres), and the scripts (`deploy.sh`, `migrate.sh`,
  `promote.sh`, `rollback.sh`, `health.sh`, `manage.sh`, ...).

## Things that are easy to get wrong

- **Never write to the services** (api-ocpp, api-gateway, api-gireve). Their models are
  `managed = False`, the router refuses to migrate them, and deployed connections run read-only
  transactions. Keep all three.
- `services/<service>/models.py` is generated by `python manage.py regenerate_models <service>`
  against the service's live database. Never edit it by hand: change the command (e.g. `SERVICES`
  for a new table's class name) and regenerate. They're excluded from pre-commit and coverage.
- In api-gateway and api-gireve, `id_db` (a uuid per row) is the Django key, and a column `id`
  that isn't the key is the field `record_id` (`db_column="id"`): the generator does both.
- Every api-ocpp query picks its tenant explicitly with `.using(ocpp_alias(tenant))`; the router's
  default (first tenant) is only a fallback.
- Field values (statuses, error codes, rejection kinds, stop reasons) are the strings api-ocpp
  stores. Check its enums (`swish-charge/api-ocpp`, `src/models/enums/`) before matching on a new one.
- Two roles (`config/roles.py`): `data` (service tables, deployments) and `support` (diagnostics,
  cases); check them with `has_role()` / `role_required()`, never with `is_staff`. Behind the auth
  proxy (`X-Forwarded-User`, `X-Forwarded-Groups`, `X-Proxy-Secret`) the roles follow the groups
  on every request (`AUTH_PROXY_DATA_GROUPS`, `AUTH_PROXY_SUPPORT_GROUPS`); without the secret the
  headers are ignored. Locally (and in tests) the Django password login works too: tests
  sign in with `force_login(user, backend="django.contrib.auth.backends.ModelBackend")`, or the
  proxy middleware signs them out.
- Tests that touch api-ocpp need `pytest.mark.django_db(databases="__all__")` and the `ocpp_tables`
  fixture (or `save`, which uses it): pytest-django only sets up the tenants' test databases when
  such a test is collected. api-gateway's and api-gireve's: the same with `service_tables`. Tests
  that need Postgres are marked `postgres` and skip on SQLite.
- Migrations run in the migrate job before each rollout (`deploy.sh`), never at container start:
  keep it that way, two replicas starting together would race.
- Answers are stored by question key in `Case.answers`; renaming a key or a choice value orphans
  old cases' answers. Add new keys/values instead, and keep `QUESTION_ORDER` in step with `QUESTIONS`.
- Production redirects to HTTPS except `/healthz` (the platform probes it over HTTP); keep the
  exemption if you add probes.

## Coding rules (all Swish repos)

- **Match the code around you**, **keep it simple**, **be precise**, **readable by the next person**,
  **verify, don't assume** (full version: `swish-charge/claude-code-setup/CLAUDE.md`).
- Full type hints (`mypy --strict` must pass), one import per line, lines up to 99 characters
  (black doesn't split strings: wrap long messages yourself).
- Logging with %-style args, never f-strings. No magic numbers (`http.HTTPStatus` for status codes).
- Don't swallow exceptions: let errors raise so Sentry sees them.
- `dict` annotations always carry key and value types (`dict[str, Any]`).
- Tests: plain functions grouped by name prefix (`test_connectors_*`, `test_transactions_*`), no
  classes; fixtures (the `make_*` factories in `tests/conftest.py`) over constants.

## Commands

```bash
python3.15 -m venv .venv && . .venv/bin/activate
pip install -r test-requirements.txt
python manage.py migrate && python manage.py seed_fake_data   # fake chargers + users support/data/admin
python manage.py runserver                          # http://localhost:8000/, search "SEED"

python -m pytest -n 4                               # SQLite, no services (Postgres runs in CI)
mypy                                                # strict
pre-commit run --all-files

scripts/compile-requirements.sh                     # after changing dependencies in pyproject.toml
python manage.py regenerate_models ocpp             # needs OCPP_DATABASE_URL (read-only) and OCPP_TENANTS
python manage.py regenerate_models gateway          # needs GATEWAY_DATABASE_URL (gireve: GIREVE_...)
```
