# swish-customer-service-diagnostics

A Django page for customer support. When a customer says **"the charger doesn't work"**, support
types the charger's identity, name or serial number and gets:

- a **verdict**: the backend sees a problem / something looks off / the charger looks healthy;
- **findings**, worst first. Each one has what the backend sees, what support or ops should do, and a
  **suggested reply** for the customer with a Copy button;
- the charger's connectors and its sessions from the last 24 h (plus any session still open).

Support doesn't need to know the tenant: the lookup searches every api-ocpp tenant schema.

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

```bash
cp .env.example .env    # OCPP_DATABASE_URL and OCPP_TENANTS at least
set -a; . ./.env; set +a
uv sync
uv run python manage.py migrate          # this app's own tables (users, sessions) only
uv run python manage.py createsuperuser
uv run python manage.py runserver        # http://localhost:8000/
```

Support users log in through the Django admin login and need `is_staff`. Manage them at `/admin/`.

Connections to api-ocpp are opened with `default_transaction_read_only=on` and the models are
unmanaged, so this app can't write to or migrate api-ocpp. Use a read-only database user in
production anyway.

## The api-ocpp models

`services/ocpp/models.py` is copied from
[swish-admin](https://github.com/fjovell-swish/swish-admin), where it is generated from api-ocpp's
SQLModel definitions. When api-ocpp's models change, regenerate it there and copy it over.

## Development

```bash
uv run pytest                       # tests, no external services needed
uv run pre-commit run --all-files   # lint
```
