# swish-customer-service-diagnostics

A guided workflow for customer support. When a customer says **"the charger doesn't work"**, the
rep finds the charger (identity, name or serial number; every api-ocpp tenant is searched) and
starts a **case**. The app then:

1. checks what api-ocpp knows about the charger (live: connection, faults, refused badges,
   sessions, maintenance, firmware);
2. **asks the rep only the questions that matter** for that charger and those answers (below);
3. writes a **diagnosis**: the likely cause with a confidence, the next steps, a **reply for the
   customer** and a **summary for the ticket**, both with a Copy button.

Cases are saved (history in the admin, with who opened them and the ticket number), so a case can
be reopened, diagnosed again with the latest data, or closed.

## The workflow

Questions (`diagnostics/workflow.py`, `QUESTIONS`), each asked only when it can change the answer:

| Question | Asked when |
| --- | --- |
| When did it happen? | always. "Before today" looks back 7 days instead of 24 h |
| Which connector? | the charger has more than one |
| What does the customer see? | always: nothing happens, refused, starts but doesn't charge, stops early, cable stuck, error on screen |
| Does the charger have power? | the charger is offline, or "nothing happens" |
| How did they start? | refused / doesn't charge / stops / other: badge, Swish app, other app or roaming card, Plug & Charge |
| The badge number | they used a badge (free text, may stay empty) |
| Did the charger react to the badge? | the backend never heard of that badge (no refusal, no session) |
| What does the screen say? | "error on screen" (free text) |
| Does the car charge on other chargers? | doesn't charge / stops early |

Diagnosis (`RULES`, in order, the first that explains the complaint wins; every finding still goes
in the ticket summary): charger not activated → offline (no power / power but no network /
unknown) → charger or connector out of service → connector faulted (advice per OCPP error code) →
cable stuck → badge refused (advice per refusal reason) → badge never heard of (reader vs.
connectivity) → app start never arrived → car not charging (power held back, car side, car refusing
power, stopped early with the stop reason, no energy delivered) → old session blocking the
connector → error on screen → the worst finding → "no fault visible", with what to ask next.

The rep can go **Back** one question, **start the questions over**, **diagnose again** with the
latest data, or **close** the case. The diagnosis is stored as written when the last question was
answered: the charger's live state moves on, the case keeps what support saw and told the customer.

## What it checks

All data is read from **api-ocpp's database** (read-only). central-system has no database, so its
view of a charger shows up through what it writes to api-ocpp (`connected`, `last_heartbeat`,
statuses, incidents).

| Check | Looks at | Flags |
| --- | --- | --- |
| Registration | `charge_points_v16.is_active` | Charger not activated (BootNotification answered Pending) |
| Connection | `connected`, `last_heartbeat`, `incidents` | Offline (and since when); marked connected but no heartbeat for 5 min |
| Stability | `incidents` (24 h) | 5+ disconnections: unstable network |
| Availability | charger and connector `availability` | Set to inoperative by ChangeAvailability |
| Connectors | `connectors_v16` status / error code | Faulted (with advice per OCPP error code), unavailable, car refusing power (`suspended_ev`), power held back (`suspended_evse`), plugged in for 15 min without a session |
| Badges | `rejected_rfids` (24 h) | Each refused badge with the reason: unknown, blocked, private charger, eMSP refusal, double auth… |
| Sessions | `transactions_v16` | Started but no energy after 10 min, open for more than 24 h (stuck), failed, ended with under 100 Wh (with the stop reason) |
| Maintenance | `maintenances` (24 h or planned) | Recorded maintenance |
| Firmware | latest `firmwares_v16` | Failed update; update in progress |

Thresholds are named constants at the top of `diagnostics/checks.py`. The checks are pure
functions over a `Snapshot` (`diagnostics/snapshot.py`), so adding one is just another function in
`CHECKS` plus its tests.

## Running locally

Python 3.15. Nothing else is needed: the local settings are hard-coded (SQLite, DEBUG on).

```bash
python3.15 -m venv .venv && . .venv/bin/activate
pip install -r test-requirements.txt
python manage.py migrate                 # this app's own tables (cases, users) only
python manage.py createsuperuser
python manage.py runserver               # http://localhost:8000/
```

Without `OCPP_DATABASE_URL` every tenant is an empty local SQLite file, so searches find nothing.
To look at real chargers, point it at an environment's api-ocpp through a **read-only** user:

```bash
OCPP_DATABASE_URL=postgres://readonly:...@host:5432/ocpp OCPP_TENANTS=public,eosgie python manage.py runserver
```

`docker compose up --build web` runs the production image locally, migrated, on the compose
Postgres (see docker-compose.yml).

## Signing in

In deployed environments support staff sign in to the user service at an **auth proxy** in front
of the app, as for central-system-new-world's read-only admin (`config/auth_proxy.py`). The proxy
forwards `X-Forwarded-User`, `X-Forwarded-Groups` and a shared secret (`X-Proxy-Secret`); members
of `AUTH_PROXY_ALLOWED_GROUPS` (default `swish-support,swish-ops`) get in, are re-checked on every
request, and no password is stored. Locally the Django login form works too.

## Read-only on api-ocpp

The api-ocpp models are unmanaged and never migrated (`config/routers.py`), and in deployed
environments every api-ocpp connection runs read-only transactions
(`default_transaction_read_only=on`): a write fails with "cannot execute UPDATE in a read-only
transaction". Use a database user with `SELECT` only anyway.

## Settings

`config/settings/`: `base.py` (shared), `local.py` (default for `manage.py` and pytest),
`ci.py` (GitHub Actions' Postgres service), `production.py` (default for wsgi; every value from the
environment, required ones listed at the top of the file).

## The api-ocpp models

`services/ocpp/models.py` is generated with Django's `inspectdb` from a live api-ocpp schema. After
api-ocpp's schema changes (an Alembic migration), regenerate it against any environment you can
reach read-only:

```bash
export OCPP_DATABASE_URL=postgres://readonly:...@host:5432/ocpp OCPP_TENANTS=public,eosgie
python manage.py regenerate_ocpp_models                          # introspects the first tenant
python manage.py regenerate_ocpp_models --database ocpp_eosgie   # or a given tenant
git diff services/ocpp/models.py                                 # review, then run the tests
```

On top of plain `inspectdb`, the command (`services/ocpp/management/commands/regenerate_ocpp_models.py`):

- keeps the class names the code imports (`charge_points_v16` → `ChargePointV16`, not
  `ChargePointsV16`). A new table gets `inspectdb`'s default name until it's added to `MODEL_NAMES`;
- reads Postgres `json` columns with `services.fields.JSONField` (`inspectdb` only maps `jsonb`);
- types api-ocpp's Postgres enums as `TextField` (`inspectdb` can't map them and would flag them as guesses);
- skips tables that aren't api-ocpp's (`spatial_ref_sys` from PostGIS, `alembic_version`).

All tenants share the same schema, so introspecting one is enough. `tsvector` search columns stay
`TextField` guesses; nothing here reads them.

## Development

The same tooling as central-system-new-world:

```bash
python -m pytest -n 4                                  # SQLite, no services (Postgres-only tests skip)
docker compose up -d postgres
DJANGO_SETTINGS_MODULE=config.settings.ci python -m pytest -n 4 --cov   # Postgres, 100% coverage
mypy                                                   # strict
pre-commit run --all-files                             # black, isort, flake8, djade, shellcheck, ...
scripts/compile-requirements.sh                        # after changing dependencies in pyproject.toml
```

Dependencies are declared in `pyproject.toml` and locked with hashes in `requirements.txt`
(runtime image) and `test-requirements.txt` (everything else). Tests use api-ocpp's real tables:
they're created from the generated models in every tenant's test database (`ocpp_tables` fixture).

CI (`.github/workflows/`):

| Workflow | Runs |
| --- | --- |
| Run tests | pytest on SQLite (twice: fixed and random order), and on Postgres with 100% coverage + `makemigrations --check` |
| Pre Commit | every hook on every file |
| Type check | `mypy` (strict) |
| Build Docker Image | builds `deploy/web.Dockerfile`, checks it runs as uid 1000, passes `check --deploy` and serves `/healthz` |
| Terraform | `terraform fmt -check` and `validate` |
| Compile requirements | recompiles the lockfiles when `pyproject.toml` changes on main, or on demand (`upgrade`) |
| Deploy | on a `vX.Y.Z` tag: build once, deploy to staging, promote the same image to production |

## Deployment

Azure Container Apps, with Terraform in `deploy/terraform/` (first-time setup in its README) and
scripts in `deploy/scripts/`. Per environment: a VNet, the `web` app, a `migrate` job, and a private
Postgres for the app's own data (cases, users). Releases are tags:

```bash
git tag v1.0.0 && git push origin v1.0.0     # staging, then production after approval
```

| Script | Does |
| --- | --- |
| `bootstrap.sh <env>` | first-time creation of an environment |
| `deploy.sh <env> [--tag T] [--plan]` | build+push (unless `--tag`), migrate on the new image, roll the app, health check |
| `migrate.sh <env>` | run the migrate job and wait for it |
| `promote.sh <from> <to> <tag>` | copy an image between registries by digest, no rebuild |
| `rollback.sh <env> <tag>` | redeploy a previous tag |
| `health.sh <env>` | `/healthz`, `check --deploy`, and a read of api-ocpp from inside the app |
| `manage.sh <env> <command>` | any `manage.py` command in the running container |
| `logs.sh <env>` | follow the app's logs |

The app needs network access to the environment's api-ocpp Postgres: allow the app's outbound IPs
(`terraform output outbound_ip_addresses`) in its firewall.
