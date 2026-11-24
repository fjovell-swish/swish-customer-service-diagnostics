# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Git rules

Commit and push straight to `main`; there are no feature branches or pull requests in this repo.
Pushing to `main` deploys nothing: it runs the CI workflows (tests, pre-commit, type check, image
build) and, when `pyproject.toml` changed, recompiles the lockfiles and pushes a commit on its own
(pull before pushing again). There's no deployment pipeline for now; never push tags unless asked.

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
  `diagnostics/admin.py`: the case history; its "Add case" leads to `/`, the one place a case
  starts. `diagnostics/forms.py`: start and answer forms.
- `diagnostics/views.py` + `templates/diagnostics/`: `/` (find a charger, start a case, latest
  cases), `/cases/<id>/` (next question or the diagnosis; Back, start over, diagnose again,
  close) and `/guide/` (how to diagnose a charger, for support reps: keep it in step with the
  workflow's pages), on the admin's look.
- `/admin/doc/` (admindocs, the header's "Documentation" link): the views' and models'
  docstrings, rendered as reStructuredText, for anyone with a role (`config/urls.py`). A model's
  page also needs Django's view permission on it, which the roles don't give: only superusers
  see those. Keep the `Case` model's and the views' docstrings accurate.
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
  environment needed), `ci` (GitHub Actions' Postgres), `production` (default for asgi and wsgi;
  every value from the environment, the required ones listed at the top).
- `config/pgbouncer/`: the database backend for the services' aliases when `PGBOUNCER` is on
  (PgBouncer in transaction pooling): every statement runs in a transaction that first sets
  `search_path` and `transaction_read_only` with SET LOCAL (the alias's `PIN`), since settings made
  when connecting don't reliably survive transaction pooling. Its real tests are `postgres`-marked.
- `mcp_api/`: the MCP API at `/mcp`. `server.py`: the tools (read-only, plain functions reusing
  `find_chargers`, `collect`, the checks, the workflow and `case_context`, so badges are masked as
  for Claude; roles checked with `caller()`). `auth.py`: `BearerTokenAuth`, the endpoint's only
  sign-in (personal tokens, `models.py`, created at `/tokens/`, `views.py`), and
  `closing_connections`: tools run in the SDK's worker threads, outside Django's request cycle, so
  they close their own database connections. Tests call the tools' `__wrapped__` with a fake
  `Context`, and the endpoint through `TestClient(build())`.
- `config/asgi.py`: the app on ASGI, as served (gunicorn + uvicorn workers): `/mcp` and lifespan
  go to the MCP app, everything else to Django. `build()` makes a new one each call: the MCP
  session manager runs once per app. `runserver` (WSGI) doesn't serve `/mcp`.
- `config/microsoft.py`: sign-in with Microsoft (Entra ID, OpenID Connect), roles from the ID
  token's groups (below); `templates/admin/login.html` puts its button first. `config/routers.py`: keeps
  the services' models off `default` and never migrates them. `config/tenancy.py`: the admin's
  tenant switcher.
- `docker/`: the image. `Dockerfile` (two stages: the hashed lockfile into a virtualenv, then the
  app on top, root-owned and read-only to uid 1000, static files collected at build time);
  `entrypoint.sh` runs the role it's given: `web`, `migrate` or `manage <command>`;
  `healthcheck.py` is the image's HEALTHCHECK. `.dockerignore` is an allowlist: a new top-level
  directory the app needs must be added there and to a `COPY` line.

## Things that are easy to get wrong

- **Never write to the services** (api-ocpp, api-gateway, api-gireve). Their models are
  `managed = False`, the router refuses to migrate them, and deployed connections run read-only
  transactions (through PgBouncer, pinned per transaction by `config/pgbouncer`). Keep all three.
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
  cases); check them with `has_role()` / `role_required()`, never with `is_staff`. Signing in with
  Microsoft sets them from the Entra groups in the ID token (`MICROSOFT_DATA_GROUPS`,
  `MICROSOFT_SUPPORT_GROUPS`: object IDs) at every sign-in; nobody without a role gets in. The ID
  token isn't signature-checked (it comes from the token endpoint), so pyjwt needs `verify_exp`,
  `verify_iss` and `verify_aud` turned on explicitly: keep them. Tests sign in with
  `force_login(user, backend="django.contrib.auth.backends.ModelBackend")`, the backend Microsoft's
  sign-in uses too, and set groups with the `role_groups` fixture.
- Tests that touch api-ocpp need `pytest.mark.django_db(databases="__all__")` and the `ocpp_tables`
  fixture (or `save`, which uses it): pytest-django only sets up the tenants' test databases when
  such a test is collected. api-gateway's and api-gireve's: the same with `service_tables`. Tests
  that need Postgres are marked `postgres` and skip on SQLite.
- Migrations run with the image's `migrate` role before a rollout, never at container start: keep
  it that way, two replicas starting together would race.
- Answers are stored by question key in `Case.answers`; renaming a key or a choice value orphans
  old cases' answers. Add new keys/values instead, and keep `QUESTION_ORDER` in step with `QUESTIONS`.
- `/mcp` skips Django's middleware and sign-in: its tools must check roles
  themselves (`caller(ctx, ...)`) and must never write. A new tool returns only what support may
  see, through the same masking as `case_context`.
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
# manage.py loads .env (python-dotenv; the shell's environment wins); pytest doesn't

python -m pytest -n 4                               # SQLite, no services (Postgres runs in CI)
mypy                                                # strict
pre-commit run --all-files

scripts/compile-requirements.sh                     # after changing dependencies in pyproject.toml
python manage.py regenerate_models ocpp             # needs OCPP_DATABASE_URL (read-only) and OCPP_TENANTS
python manage.py regenerate_models gateway          # needs GATEWAY_DATABASE_URL (gireve: GIREVE_...)
```
