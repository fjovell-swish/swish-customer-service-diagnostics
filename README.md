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

It also replaces the former swish-admin: people with the `data` role get every table of api-ocpp
(per tenant), api-gateway and api-gireve in the admin, read-only, and the deployments page (what
each service runs in staging and production, from GitHub Actions and Kubernetes).

For support reps, the app has a short guide, **How to diagnose a charger** (`/guide/`, linked
from the diagnostics page). The header's **Documentation** link (`/admin/doc/`, Django's
admindocs) describes the views and, for superusers, the models, from their docstrings.

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

## Claude's assessment and the Jira escalation

Once a case is diagnosed, **Ask Claude for an assessment** sends the whole case to Claude
(`diagnostics/assistant.py`): the charger and its connectors as api-ocpp stores them, the
incidents, refused badges, sessions, maintenance and firmware of the period looked at, the checks'
findings, the rep's answers and the rules' diagnosis. Claude answers with what's going on (citing
the data), the likely cause with a confidence, whether it agrees with the rules, **what support can
do**, a reply for the customer, and whether the case **needs the tech team**, with a Jira ticket's
title and description. The case keeps the assessment (and the model that wrote it); going Back or
starting the questions over drops it, since it was about the old answers.

**Create the Jira ticket** (`diagnostics/jira.py`) files Claude's ticket in Jira (by default an
`[System] Incident` in `ROT`, labelled `jira_escalated`, `support-diagnostics`), with a link to the
case and the diagnostics' summary, once per case; the case shows the issue. The button is the
default one when Claude says support can't solve it, and still there when it says they can.

What Claude never gets: drivers' emails, the charger's SIM and IP, firmware signatures. Badge
numbers are masked to their last 4 characters everywhere (rows, answers, the rules' texts).
Without `ANTHROPIC_API_KEY`, or the Jira account (`JIRA_EMAIL`, `JIRA_API_TOKEN`), the buttons are
hidden. If Claude or Jira fails, the rep gets a message and the error goes to Sentry.

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
python manage.py seed_fake_data          # fake chargers, and users support, data, admin (password = name)
python manage.py runserver               # http://localhost:8000/, search "SEED"
```

Without `OCPP_DATABASE_URL` every tenant is a local SQLite file. `seed_fake_data` (re)creates
api-ocpp's tables there and fills them with fake chargers, one per problem the workflow
diagnoses, with timestamps relative to now. Run it again whenever you want fresh data:

| Charger | Tenant | Shows |
| --- | --- | --- |
| `SEED-OK-01` | first | nothing wrong (two connectors, a normal session) |
| `SEED-OFFLINE-01` | first | offline for 3 h |
| `SEED-SILENT-01` | first | connected, but no heartbeat for 30 min |
| `SEED-FLAKY-01` | first | 6 disconnections today |
| `SEED-FAULT-01` | first | connector 1 faulted (`ground_failure`), connector 2 fine |
| `SEED-BADGE-01` | first | private charger, two refused badges, cable plugged in without a session |
| `SEED-CAR-01` | first | car not taking power (`suspended_ev`), session with no energy |
| `SEED-STUCK-01` | first | a session open for 3 days |
| `SEED-INACTIVE-01` | first | not activated |
| `SEED-OFFSERVICE-01` | first | set to inoperative |
| `SEED-FIRMWARE-01` | first | failed firmware update |
| `SEED-NOCONN-01` | first | no connector reported (never sent a StatusNotification) |
| `SEED-SIGNAL-01` | first | connector available but reporting `weak_signal` |
| `SEED-FAILED-01` | first | a failed session |
| `SEED-UPDATING-01` | first | firmware update downloading, connector unavailable |
| `SEED-LASTWEEK-01` | first | healthy today; answer "Before today" to see a refused badge and a session with no energy |
| `SEED-NETWORK-01` | first | for Claude's assessment: sessions end `ev_disconnected` right as the charger drops off the network. Answer stops early / Swish app / charges elsewhere: the rules blame the car, the timestamps point at the network |
| `SEED-TENANT-01` | second | offline, faulted, a badge refused by its eMSP, recent maintenance |
| `SEED-TENANT-02` | second | power held back (`suspended_evse`), a session stopped early |

It only ever writes to local SQLite: with `OCPP_DATABASE_URL` set it refuses to run. It also
gives the local api-gateway and api-gireve SQLite files their tables, empty, so the admin shows
them; set `GATEWAY_DATABASE_URL` / `GIREVE_DATABASE_URL` (read-only users) to browse real ones.

To look at real chargers, point it at an environment's api-ocpp through a **read-only** user:

```bash
OCPP_DATABASE_URL=postgres://readonly:...@host:5432/ocpp OCPP_TENANTS=public,eosgie python manage.py runserver
```

Or put them in `.env` (`cp .env.example .env`, git-ignored): `manage.py` reads it by itself, and a
variable set in the shell wins over it. The same goes for the Claude key and the Jira account.

`docker compose up --build web` runs the production image locally, migrated, on the compose
Postgres (see docker-compose.yml).

## Signing in, and the two ways in

Two roles (`config/roles.py`), and someone can have both:

| Role | Gets | Granted by (proxy groups) |
| --- | --- | --- |
| `support` (customer service) | the diagnostics workflow (`/`) and the case history | `AUTH_PROXY_SUPPORT_GROUPS`, default `swish-support,swish-ops` |
| `data` (query the data) | every service table in the admin, read-only, with the tenant switcher, and the deployments page | `AUTH_PROXY_DATA_GROUPS`, default `swish-data,swish-ops` |

`/` lands people with only `data` on the admin's tables. Each role sees only its part of the admin
index and header.

In deployed environments people sign in to the user service at an **auth proxy** in front of the
app, as for central-system-new-world's read-only admin (`config/auth_proxy.py`). The proxy
forwards `X-Forwarded-User`, `X-Forwarded-Groups` and a shared secret (`X-Proxy-Secret`); a user's
roles follow their groups on every request (losing every role signs them out), and no password is
stored. Locally the Django login form works too, and roles are the Django groups `data` and
`support`: `seed_fake_data` creates `support`, `data` and `admin` (superuser: both).

## Read-only on the services

The api-ocpp, api-gateway and api-gireve models are unmanaged and never migrated
(`config/routers.py`), and in deployed environments every connection to them runs read-only
transactions
(`default_transaction_read_only=on`): a write fails with "cannot execute UPDATE in a read-only
transaction". Use a database user with `SELECT` only anyway.

**Through PgBouncer** (Azure's, port 6432, transaction pooling), set `PGBOUNCER=true`
(Terraform: `pgbouncer = true`). Consecutive statements can then run on different server
connections, so the tenant's `search_path` and the read-only mode set when connecting would only
follow if PgBouncer tracks them. With the flag, the services' aliases use `config/pgbouncer`
instead: every statement runs in a short transaction that first does `SET LOCAL search_path` and
`SET LOCAL transaction_read_only`, and server-side cursors are off. The app's own database isn't
affected. Without the flag, connect directly (port 5432).

## Settings

`config/settings/`: `base.py` (shared), `local.py` (default for `manage.py` and pytest),
`ci.py` (GitHub Actions' Postgres service), `production.py` (default for wsgi; every value from the
environment, required ones listed at the top of the file).

## The services' models

`services/<service>/models.py` (`ocpp`, `gateway`, `gireve`) are generated with Django's
`inspectdb` from the service's live database. After a service's schema changes, regenerate its
models against any environment you can reach read-only:

```bash
export OCPP_DATABASE_URL=postgres://readonly:...@host:5432/ocpp OCPP_TENANTS=public,eosgie
python manage.py regenerate_models ocpp                          # introspects the first tenant
python manage.py regenerate_models ocpp --database ocpp_eosgie   # or a given tenant
GATEWAY_DATABASE_URL=postgres://readonly:...@host:5432/gateway python manage.py regenerate_models gateway
GIREVE_DATABASE_URL=postgres://readonly:...@host:5432/gireve python manage.py regenerate_models gireve
git diff services/                                               # review, then run the tests
```

On top of plain `inspectdb`, the command (`services/ocpp/management/commands/regenerate_models.py`):

- keeps the class names the code imports (`charge_points_v16` → `ChargePointV16`, not
  `ChargePointsV16`; api-gateway's and api-gireve's are the services' own SQLModel class
  names). A new table gets `inspectdb`'s default name until it's added to `SERVICES`;
- reads Postgres `json` columns with `services.fields.JSONField` (`inspectdb` only maps `jsonb`);
- types Postgres enums as `TextField` (`inspectdb` can't map them and would flag them as guesses);
- skips tables that aren't the service's (`spatial_ref_sys` from PostGIS, `alembic_version`);
- fits api-gateway's and api-gireve's keys to Django: a composite key that includes the row uuid
  `id_db` (e.g. `(id, id_db)`) becomes `id_db` alone, since the admin can't show composite keys;
  an `id` column that isn't the key becomes `record_id` (`db_column="id"`; Django reserves `id`
  for the key), and foreign keys to it use `to_field="record_id"`. Link tables (two foreign keys)
  keep their composite key and stay out of the admin.

All api-ocpp tenants share the same schema, so introspecting one is enough. `tsvector` search
columns stay `TextField` guesses; nothing here reads them.

## Development

The same tooling as central-system-new-world:

```bash
python -m pytest -n 4                                  # SQLite, no services (Postgres-only tests skip)
mypy                                                   # strict
pre-commit run --all-files                             # black, isort, flake8, djade, shellcheck, ...
scripts/compile-requirements.sh                        # after changing dependencies in pyproject.toml
```

Dependencies are declared in `pyproject.toml` and locked with hashes in `requirements.txt`
(runtime image) and `test-requirements.txt` (everything else). Tests use api-ocpp's real tables:
they're created from the generated models in every tenant's test database (`ocpp_tables` fixture).

Locally the tests run on SQLite. CI runs them on SQLite and on Postgres, where the 100% coverage
gate applies (`.github/workflows/`):

| Workflow | Runs |
| --- | --- |
| Run tests | pytest on SQLite (fixed and random order), and on Postgres with 100% coverage + `makemigrations --check` |
| Pre Commit | every hook on every file |
| Type check | `mypy` (strict) |
| Build Docker Image | builds `docker/Dockerfile`, checks it runs as uid 1000, passes `check --deploy` and serves `/healthz` |
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

The app needs network access to the environment's api-ocpp Postgres (and api-gateway's and
api-gireve's, when configured): allow the app's outbound IPs (`terraform output
outbound_ip_addresses`) in their firewalls. The secrets each one needs are listed in
`deploy/terraform/README.md`.
