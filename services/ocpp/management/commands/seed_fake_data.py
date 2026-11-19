"""
Fill the LOCAL api-ocpp databases with fake chargers to try the workflow on, one per problem the
diagnosis knows about (offline, faulted, refused badge, car not charging, ...).

    python manage.py migrate
    python manage.py seed_fake_data
    python manage.py runserver        # sign in (below), search "SEED"

It also creates a local user per way in (password = username): `support` (customer service:
diagnostics and cases), `data` (query the data: the tables and deployments) and `admin` (both,
and the admin's users).

It (re)creates api-ocpp's tables from the generated models in every tenant's local SQLite file,
so it can run again at any time. It refuses anything but SQLite: this app must never write to a
real api-ocpp (with OCPP_DATABASE_URL set, the tenants are a real, read-only Postgres).
"""

import uuid
from datetime import datetime
from datetime import timedelta
from typing import Any

from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import connections
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import Model
from django.utils import timezone

from config.roles import DATA
from config.roles import SUPPORT
from config.roles import set_roles
from services.ocpp.models import ChargePointV16
from services.ocpp.models import ConnectorV16
from services.ocpp.models import FirmwareV16
from services.ocpp.models import Incident
from services.ocpp.models import Maintenance
from services.ocpp.models import RejectedRfid
from services.ocpp.models import TransactionV16

# Local users, one per way in (config/roles.py): username (= password) -> roles; None: superuser.
USERS: dict[str, set[str] | None] = {"support": {SUPPORT}, "data": {DATA}, "admin": None}
# A finished session's energy, in Wh: enough not to look like "no energy".
NORMAL_SESSION_WH = 18_000.0
FLAPPING_DISCONNECTS = 6


def is_local(connection: BaseDatabaseWrapper) -> bool:
    return connection.vendor == "sqlite"


class Seeder:
    """Writes one tenant's fake chargers. Times are relative to `now`, so the data looks fresh."""

    def __init__(self, alias: str, now: datetime) -> None:
        self.alias = alias
        self.now = now
        self.transaction_id = 0

    def ago(self, **delta: float) -> datetime:
        return self.now - timedelta(**delta)

    def save[M: Model](self, instance: M) -> M:
        instance.save(using=self.alias, force_insert=True)
        return instance

    def charge_point(self, identity: str, name: str, **fields: Any) -> ChargePointV16:
        values: dict[str, Any] = {
            "id": uuid.uuid4(),
            "identity": identity,
            "charger_name": name,
            "customer_name": "Fake Parkings Inc.",
            "address": "1 Rue de l'Exemple",
            "postal_code": "75001",
            "city": "Paris",
            "vendor": "FakeVendor",
            "model": "FV-22",
            "serial_number": f"SN-{identity}",
            "firmware_version": "2.4.1",
            "iccid": "8933000000000000001",
            "charger_type": "PUBLIC",
            "ocpp_version": "OcppV16",
            "is_active": True,
            "connected": True,
            "last_heartbeat": self.ago(seconds=20),
            "availability": "operative",
            "status": "available",
            "super_charger": False,
            "is_plug_and_charge": False,
            "is_double_authentication": False,
            "availability_rating_enabled": False,
            "created_at": self.ago(days=200),
        }
        return self.save(ChargePointV16(**(values | fields)))

    def connector(self, charge_point: ChargePointV16, index: int, **fields: Any) -> ConnectorV16:
        values: dict[str, Any] = {
            "id": uuid.uuid4(),
            "charge_point": charge_point,
            "index": index,
            "status": "available",
            "error_code": "no_error",
            "availability": "operative",
            "connected": True,
            "connector_type": "IEC_62196_T2",
            "power_type": "AC_3_PHASE",
            "updated_at": self.ago(minutes=5),
        }
        return self.save(ConnectorV16(**(values | fields)))

    def transaction(self, connector: ConnectorV16, **fields: Any) -> TransactionV16:
        self.transaction_id += 1
        started = fields.pop("started_at", self.ago(hours=3))
        values: dict[str, Any] = {
            "id": self.transaction_id,
            "uid": uuid.uuid4(),
            "connector": connector,
            "connector_index": connector.index,
            "timestamp": started.isoformat(),
            "work_place": "PUBLIC",
            "status": "FINISHED",
            "id_tag": "BADGE-OK",
            "created_at": started,
            "started_at": started,
            "ended_at": started + timedelta(hours=1),
            "energy_delivered": NORMAL_SESSION_WH,
            "reason": "local",
        }
        return self.save(TransactionV16(**(values | fields)))

    def disconnected(self, charge_point: ChargePointV16, at: datetime) -> None:
        self.save(
            Incident(
                id=uuid.uuid4(),
                identity=charge_point.identity,
                event="disconnected",
                started_at=at,
            )
        )

    def refused(self, charge_point: ChargePointV16, badge: str, kind: str, **fields: Any) -> None:
        values: dict[str, Any] = {
            "id": uuid.uuid4(),
            "identity": charge_point.identity,
            "id_token": badge,
            "reason_kind": kind,
            "created_at": self.ago(minutes=40),
        }
        self.save(RejectedRfid(**(values | fields)))

    def seed_public(self) -> None:
        healthy = self.charge_point("SEED-OK-01", "Healthy charger")
        connector = self.connector(healthy, 1)
        self.connector(healthy, 2, status="charging")
        self.transaction(connector)

        offline = self.charge_point(
            "SEED-OFFLINE-01", "Offline charger", connected=False, last_heartbeat=self.ago(hours=3)
        )
        self.connector(offline, 1)
        self.disconnected(offline, self.ago(hours=3))

        silent = self.charge_point(
            "SEED-SILENT-01", "Connected but silent", last_heartbeat=self.ago(minutes=30)
        )
        self.connector(silent, 1)

        flaky = self.charge_point("SEED-FLAKY-01", "Unstable connection")
        self.connector(flaky, 1)
        for hours in range(FLAPPING_DISCONNECTS):
            self.disconnected(flaky, self.ago(hours=hours * 3 + 1))

        faulted = self.charge_point("SEED-FAULT-01", "Faulted connector", status="faulted")
        self.connector(faulted, 1, status="faulted", error_code="ground_failure")
        self.connector(faulted, 2)

        badges = self.charge_point("SEED-BADGE-01", "Refused badges", charger_type="PRIVATE")
        self.connector(badges, 1, status="preparing", updated_at=self.ago(minutes=40))
        self.refused(badges, "BADGE-PRIVATE", "PRIVATE_CHARGER")
        self.refused(badges, "BADGE-UNKNOWN", "RFID_DOES_NOT_EXIST", created_at=self.ago(hours=2))

        car = self.charge_point("SEED-CAR-01", "Car not taking power")
        connector = self.connector(
            car, 1, status="suspended_ev", last_suspended_ev=self.ago(minutes=30)
        )
        self.transaction(
            connector,
            status="PENDING",
            started_at=self.ago(minutes=30),
            ended_at=None,
            energy_delivered=None,
            reason=None,
        )

        stuck = self.charge_point("SEED-STUCK-01", "Session open for days")
        connector = self.connector(stuck, 1, status="finishing")
        self.transaction(
            connector, status="ONGOING", started_at=self.ago(days=3), ended_at=None, reason=None
        )

        self.connector(self.charge_point("SEED-INACTIVE-01", "Not activated", is_active=False), 1)

        out_of_service = self.charge_point(
            "SEED-OFFSERVICE-01", "Out of service", availability="inoperative"
        )
        self.connector(out_of_service, 1, status="unavailable", availability="inoperative")

        firmware = self.charge_point("SEED-FIRMWARE-01", "Failed firmware update")
        self.connector(firmware, 1)
        self.save(
            FirmwareV16(
                id=uuid.uuid4(),
                charge_point=firmware,
                status="download_failed",
                firmware_version="2.5.0",
                error="HTTP 404 on the firmware URL",
                created_at=self.ago(hours=5),
                updated_at=self.ago(hours=4),
            )
        )

    def seed_other_tenant(self) -> None:
        # Searching "SEED" also finds these: support doesn't need to know the tenant.
        broken = self.charge_point(
            "SEED-TENANT-01",
            "Other tenant: offline and faulted",
            connected=False,
            status="faulted",
            last_heartbeat=self.ago(hours=6),
        )
        self.connector(broken, 1, status="faulted", error_code="over_current_failure")
        self.disconnected(broken, self.ago(hours=6))
        self.refused(broken, "BADGE-EMSP", "EMSP_REJECTION", reason="Token blocked by its eMSP")
        self.save(
            Maintenance(
                id=uuid.uuid4(),
                identity=broken.identity,
                maintainer="Fake Technician",
                reason="Replaced the residual-current device",
                maintenance_at=self.ago(hours=20),
            )
        )

        stops = self.charge_point("SEED-TENANT-02", "Other tenant: power held back, stops early")
        connector = self.connector(stops, 1, status="suspended_evse")
        self.transaction(connector, energy_delivered=50.0, reason="power_loss")


class Command(BaseCommand):
    help = "Fill the local api-ocpp databases (SQLite) with fake chargers. Never a real one."

    def handle(self, **options: Any) -> None:
        aliases = [f"ocpp_{tenant}" for tenant in settings.OCPP_TENANTS]
        not_local = [alias for alias in aliases if not is_local(connections[alias])]
        if not_local:
            raise CommandError(
                f"Refusing to write to {', '.join(not_local)}: only local SQLite tenants are"
                " seeded. Unset OCPP_DATABASE_URL to use them."
            )

        now = timezone.now()
        for position, alias in enumerate(aliases):
            self.reset_tables(connections[alias])
            seeder = Seeder(alias, now)
            # The first tenant gets every scenario; the others show the cross-tenant search.
            if position == 0:
                seeder.seed_public()
            else:
                seeder.seed_other_tenant()
            count = ChargePointV16.objects.using(alias).count()
            self.stdout.write(f"{alias}: {count} fake chargers")

        for username, roles in USERS.items():
            if User.objects.filter(username=username).exists():
                continue
            if roles is None:
                User.objects.create_superuser(username, f"{username}@example.com", username)
            else:
                user = User.objects.create_user(username, password=username, is_staff=True)
                set_roles(user, roles)
            self.stdout.write(f"Created the user {username} / {username}")
        self.stdout.write(self.style.SUCCESS('Done: search "SEED" on the diagnostics page.'))

    def reset_tables(self, connection: BaseDatabaseWrapper) -> None:
        models = list(apps.get_app_config("ocpp").get_models())
        existing = set(connection.introspection.table_names())
        with connection.schema_editor() as editor:
            for model in models:
                if model._meta.db_table in existing:
                    editor.delete_model(model)
            for model in models:
                editor.create_model(model)
