import uuid
from collections.abc import Callable
from datetime import datetime
from datetime import timedelta
from datetime import UTC
from typing import Any

import pytest
from django.contrib.auth.models import User
from django.test import Client

from diagnostics.snapshot import Snapshot
from services.ocpp.models import ChargePointV16
from services.ocpp.models import ConnectorV16
from services.ocpp.models import FirmwareV16
from services.ocpp.models import Incident
from services.ocpp.models import RejectedRfid
from services.ocpp.models import TransactionV16


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


@pytest.fixture
def make_charge_point(now: datetime) -> Callable[..., ChargePointV16]:
    def factory(**overrides: Any) -> ChargePointV16:
        values: dict[str, Any] = {
            "id": uuid.uuid4(),
            "identity": "FR*SWI*CP001",
            "charger_name": "Parking level -1",
            "customer_name": "ACME",
            "charger_type": "PUBLIC",
            "is_active": True,
            "connected": True,
            "last_heartbeat": now - timedelta(seconds=20),
            "availability": "operative",
            "status": "available",
            "iccid": "8933",
        }
        return ChargePointV16(**(values | overrides))

    return factory


@pytest.fixture
def make_connector(now: datetime) -> Callable[..., ConnectorV16]:
    def factory(**overrides: Any) -> ConnectorV16:
        values: dict[str, Any] = {
            "id": uuid.uuid4(),
            "index": 1,
            "status": "available",
            "error_code": "no_error",
            "availability": "operative",
            "connected": True,
            "updated_at": now - timedelta(minutes=1),
        }
        return ConnectorV16(**(values | overrides))

    return factory


@pytest.fixture
def make_transaction(now: datetime) -> Callable[..., TransactionV16]:
    def factory(**overrides: Any) -> TransactionV16:
        values: dict[str, Any] = {
            "id": 1234,
            "status": "FINISHED",
            "id_tag": "BADGE1",
            "created_at": now - timedelta(hours=2),
            "started_at": now - timedelta(hours=2),
            "ended_at": now - timedelta(hours=1),
            "energy_delivered": 12000.0,
            "reason": "local",
        }
        return TransactionV16(**(values | overrides))

    return factory


@pytest.fixture
def make_incident(now: datetime) -> Callable[..., Incident]:
    def factory(**overrides: Any) -> Incident:
        values: dict[str, Any] = {"event": "disconnected", "identity": "FR*SWI*CP001", "started_at": now}
        return Incident(**(values | overrides))

    return factory


@pytest.fixture
def make_rejection(now: datetime) -> Callable[..., RejectedRfid]:
    def factory(**overrides: Any) -> RejectedRfid:
        values: dict[str, Any] = {
            "id_token": "BADGE9",
            "reason_kind": "RFID_DOES_NOT_EXIST",
            "identity": "FR*SWI*CP001",
            "created_at": now - timedelta(minutes=30),
        }
        return RejectedRfid(**(values | overrides))

    return factory


@pytest.fixture
def make_firmware(now: datetime) -> Callable[..., FirmwareV16]:
    def factory(**overrides: Any) -> FirmwareV16:
        values: dict[str, Any] = {
            "status": "installed",
            "firmware_version": "2.1.0",
            "created_at": now - timedelta(hours=1),
            "updated_at": now - timedelta(minutes=50),
        }
        return FirmwareV16(**(values | overrides))

    return factory


@pytest.fixture
def make_snapshot(
    make_charge_point: Callable[..., ChargePointV16], make_connector: Callable[..., ConnectorV16]
) -> Callable[..., Snapshot]:
    def factory(**overrides: Any) -> Snapshot:
        values: dict[str, Any] = {
            "tenant": "public",
            "charge_point": make_charge_point(),
            "connectors": [make_connector()],
        }
        return Snapshot(**(values | overrides))

    return factory


@pytest.fixture
def admin_client(db: None) -> Client:
    user = User.objects.create_superuser("support", "support@example.com", "password")
    client = Client()
    client.force_login(user)
    return client
