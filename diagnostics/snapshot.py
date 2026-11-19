# Everything api-ocpp knows about one charger, read in one go so the checks stay pure functions.
#
# Support rarely knows which tenant a charger belongs to, so the lookup searches every tenant
# schema and the snapshot is read from the one where the charger was found.
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta

from django.conf import settings
from django.db.models import Q

from services.ocpp.models import ChargePointV16
from services.ocpp.models import ConnectorV16
from services.ocpp.models import FirmwareV16
from services.ocpp.models import Incident
from services.ocpp.models import Maintenance
from services.ocpp.models import RejectedRfid
from services.ocpp.models import TransactionV16

# How far back the checks look at incidents, badges, transactions and maintenance.
LOOKBACK = timedelta(hours=24)
MAX_MATCHES = 20
MAX_ROWS = 50


@dataclass
class ChargerMatch:
    tenant: str
    charge_point: ChargePointV16


@dataclass
class Snapshot:
    tenant: str
    charge_point: ChargePointV16
    connectors: list[ConnectorV16] = field(default_factory=list)
    incidents: list[Incident] = field(default_factory=list)
    rejected_rfids: list[RejectedRfid] = field(default_factory=list)
    transactions: list[TransactionV16] = field(default_factory=list)
    maintenances: list[Maintenance] = field(default_factory=list)
    firmwares: list[FirmwareV16] = field(default_factory=list)


def ocpp_alias(tenant: str) -> str:
    return f"ocpp_{tenant}"


def find_chargers(query: str) -> list[ChargerMatch]:
    """Chargers matching an identity exactly, or else a name, identity or serial fragment.

    Every tenant is searched.
    """
    query = query.strip()
    if not query:
        return []
    matches: list[ChargerMatch] = []
    for tenant in settings.OCPP_TENANTS:
        charge_points = ChargePointV16.objects.using(ocpp_alias(tenant))
        exact = list(charge_points.filter(identity=query))
        if exact:
            matches.extend(ChargerMatch(tenant, charge_point) for charge_point in exact)
            continue
        fuzzy = charge_points.filter(
            Q(identity__icontains=query)
            | Q(charger_name__icontains=query)
            | Q(serial_number__icontains=query)
            | Q(charge_box_serial_number__icontains=query)
        ).order_by("identity")[:MAX_MATCHES]
        matches.extend(ChargerMatch(tenant, charge_point) for charge_point in fuzzy)
    # An exact identity hit anywhere beats fragments elsewhere.
    exact_matches = [match for match in matches if match.charge_point.identity == query]
    return exact_matches or matches[:MAX_MATCHES]


def collect(
    tenant: str, charge_point: ChargePointV16, now: datetime, lookback: timedelta = LOOKBACK
) -> Snapshot:
    alias = ocpp_alias(tenant)
    since = now - lookback
    connectors = list(
        ConnectorV16.objects.using(alias).filter(charge_point_id=charge_point.id).order_by("index")
    )
    connector_ids = [connector.id for connector in connectors]
    # Ongoing transactions are kept whatever their age: an old one is exactly the stuck session
    # to spot.
    transactions = (
        TransactionV16.objects.using(alias)
        .filter(connector_id__in=connector_ids)
        .filter(Q(created_at__gte=since) | Q(status__in=["PENDING", "ONGOING"]))
        .order_by("-created_at")[:MAX_ROWS]
    )
    return Snapshot(
        tenant=tenant,
        charge_point=charge_point,
        connectors=connectors,
        incidents=list(
            Incident.objects.using(alias)
            .filter(identity=charge_point.identity, started_at__gte=since)
            .order_by("-started_at")[:MAX_ROWS]
        ),
        rejected_rfids=list(
            RejectedRfid.objects.using(alias)
            .filter(identity=charge_point.identity, created_at__gte=since)
            .order_by("-created_at")[:MAX_ROWS]
        ),
        transactions=list(transactions),
        maintenances=list(
            Maintenance.objects.using(alias)
            .filter(identity=charge_point.identity, maintenance_at__gte=since)
            .order_by("-maintenance_at")[:MAX_ROWS]
        ),
        firmwares=list(
            FirmwareV16.objects.using(alias)
            .filter(charge_point_id=charge_point.id)
            .order_by("-created_at")[:1]
        ),
    )
