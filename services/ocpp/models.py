"""Unmanaged models for the api-ocpp database.

COPIED from fjovell-swish/swish-admin (services/ocpp/models.py), where they are generated from
api-ocpp's SQLModel definitions. Don't edit by hand: refresh them there and copy the file over.
"""

import uuid  # noqa: F401

from django.db import models

from services import fields


class Authorization(models.Model):
    authorization_id = models.TextField()
    id_tag = models.TextField()
    evse_id = models.IntegerField()
    time_limit = models.IntegerField(null=True, blank=True)
    energy_limit = models.IntegerField(null=True, blank=True)
    battery_percentage_limit = models.IntegerField(null=True, blank=True)
    total_cost_limit = models.FloatField(null=True, blank=True)
    roaming_token_uid = models.TextField(null=True, blank=True)
    provider = models.CharField(max_length=19, choices=[("SWISH", "SWISH"), ("GIREVE", "GIREVE"), ("GETAWAY", "GETAWAY"), ("MOBILE_B2C_APP", "MOBILE_B2C_APP"), ("MOBILE_B2B_APP", "MOBILE_B2B_APP"), ("INTERFACE_PLATTFORM", "INTERFACE_PLATTFORM"), ("OTHER", "OTHER")], null=True, blank=True)
    status = models.CharField(max_length=7, choices=[("valid", "valid"), ("expired", "expired"), ("invalid", "invalid")], null=True, blank=True)
    authorization_reference = models.CharField(max_length=15, choices=[("RFID", "RFID"), ("RFID_BADGE_PRO", "RFID_BADGE_PRO"), ("SWISH_PRO_APP", "SWISH_PRO_APP"), ("MAC_ADDRESS", "MAC_ADDRESS"), ("SWISH_APP_B2C", "SWISH_APP_B2C"), ("SWISH_APP_B2B", "SWISH_APP_B2B"), ("SWISH_INTERFACE", "SWISH_INTERFACE"), ("VIRTUAL_RFID", "VIRTUAL_RFID"), ("GIREVE_OCPI", "GIREVE_OCPI"), ("CACHE", "CACHE"), ("OTHER", "OTHER")], null=True, blank=True)
    additional_properties = fields.JSONField(null=True, blank=True)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "authorizations"
        verbose_name = "authorizations"
        verbose_name_plural = "authorizations"


class ChargePointProfileLink(models.Model):
    pk = models.CompositePrimaryKey('connector_id', 'charging_profile_id')
    connector = models.ForeignKey("ConnectorV16", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+", db_column="connector_id")
    charging_profile = models.ForeignKey("ChargingProfile", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+", db_column="charging_profile_id")
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "charge_point_profile_link"
        verbose_name = "charge point profile link"
        verbose_name_plural = "charge point profile link"


class ChargePointTariffLink(models.Model):
    pk = models.CompositePrimaryKey('charge_point_id', 'tariff_id')
    charge_point = models.ForeignKey("ChargePointV16", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+", db_column="charge_point_id")
    tariff = models.ForeignKey("Tariff", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+", db_column="tariff_id")
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "charge_point_tariff_link"
        verbose_name = "charge point tariff link"
        verbose_name_plural = "charge point tariff link"


class ChargePointV16(models.Model):
    model = models.TextField(null=True, blank=True)
    serial_number = models.TextField(null=True, blank=True)
    charge_box_serial_number = models.TextField(null=True, blank=True)
    vendor = models.TextField(null=True, blank=True)
    meter_serial_number = models.TextField(null=True, blank=True)
    firmware_version = models.TextField(null=True, blank=True)
    iccid = models.TextField(null=True, blank=True)
    imsi = models.TextField(null=True, blank=True)
    meter_type = models.TextField(null=True, blank=True)
    is_active = models.BooleanField()
    ocpp_version = models.CharField(max_length=8, choices=[("OcppV201", "OcppV201"), ("OcppV16", "OcppV16")])
    charger_type = models.CharField(max_length=7, choices=[("PRIVATE", "PRIVATE"), ("PUBLIC", "PUBLIC"), ("ROAMING", "ROAMING")])
    availability = models.CharField(max_length=11, choices=[("inoperative", "inoperative"), ("operative", "operative")])
    status = models.CharField(max_length=14, choices=[("available", "available"), ("preparing", "preparing"), ("charging", "charging"), ("suspended_evse", "suspended_evse"), ("suspended_ev", "suspended_ev"), ("finishing", "finishing"), ("reserved", "reserved"), ("unavailable", "unavailable"), ("faulted", "faulted")])
    host = models.TextField(null=True, blank=True)
    tenant_id = models.TextField(null=True, blank=True)
    coordinates = fields.JSONField(null=True, blank=True)
    country = models.TextField(null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    super_charger = models.BooleanField()
    customer_name = models.TextField(null=True, blank=True)
    charger_name = models.TextField(null=True, blank=True)
    ip_address = models.TextField(null=True, blank=True)
    poc_type = models.CharField(max_length=5, choices=[("AC", "AC"), ("DC", "DC"), ("OTHER", "OTHER")], null=True, blank=True)
    city = models.TextField(null=True, blank=True)
    postal_code = models.TextField(null=True, blank=True)
    list_version = models.IntegerField(null=True, blank=True)
    connected = models.BooleanField()
    max_power = models.FloatField(null=True, blank=True)
    is_plug_and_charge = models.BooleanField()
    is_double_authentication = models.BooleanField()
    availability_rating_enabled = models.BooleanField()
    availability_rating_start_at = models.DateTimeField(null=True, blank=True)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    identity = models.TextField(unique=True)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    last_heartbeat = models.DateTimeField(null=True, blank=True)
    location = models.ForeignKey("Location", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+", db_column="location_id", null=True, blank=True)

    class Meta:
        managed = False
        db_table = "charge_points_v16"
        verbose_name = "charge points v16"
        verbose_name_plural = "charge points v16"


class ChargePointV201(models.Model):
    imei = models.TextField(unique=True)
    charge_point_id = models.TextField(unique=True)
    is_active = models.BooleanField()
    vendor_name = models.TextField()
    model = models.TextField()
    serial_number = models.TextField(null=True, blank=True)
    firmware_version = models.TextField(null=True, blank=True)
    status = models.TextField(null=True, blank=True)
    iccid = models.TextField(null=True, blank=True)
    imsi = models.TextField(null=True, blank=True)
    updated_at = models.DateTimeField()
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)

    class Meta:
        managed = False
        db_table = "chargepoint_v201"
        verbose_name = "chargepoint v201"
        verbose_name_plural = "chargepoint v201"


class ChargeSession(models.Model):
    start_time = models.DateTimeField(null=True, blank=True)
    evse_id = models.IntegerField()
    duration = models.FloatField()
    starting_transaction_energy = models.FloatField()
    energy = models.FloatField()
    end_time = models.DateTimeField(null=True, blank=True)
    duration_type = models.TextField()
    updated_at = models.DateTimeField(null=True, blank=True)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    created_at = models.DateTimeField(null=True, blank=True)
    connector_id = models.UUIDField()
    transaction = models.ForeignKey("TransactionV16", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+", db_column="transaction_id", null=True, blank=True)

    class Meta:
        managed = False
        db_table = "charge_sessions"
        verbose_name = "charge sessions"
        verbose_name_plural = "charge sessions"


class ChargingProfile(models.Model):
    name = models.TextField(null=True, blank=True)
    purpose = models.CharField(max_length=24, choices=[("charge_point_max_profile", "charge_point_max_profile"), ("tx_default_profile", "tx_default_profile"), ("tx_profile", "tx_profile")])
    kind = models.CharField(max_length=9, choices=[("absolute", "absolute"), ("recurring", "recurring"), ("relative", "relative")])
    recurrency = models.CharField(max_length=6, choices=[("daily", "daily"), ("weekly", "weekly")], null=True, blank=True)
    stack_level = models.IntegerField()
    transaction_id = models.IntegerField(null=True, blank=True)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_to = models.DateTimeField(null=True, blank=True)
    charging_schedule = fields.JSONField(null=True, blank=True)
    start_schedule = models.DateTimeField(null=True, blank=True)
    min_rate = models.FloatField(null=True, blank=True)
    rate_unit = models.CharField(max_length=5, choices=[("watts", "watts"), ("amps", "amps")])
    duration = models.IntegerField(null=True, blank=True)
    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "charging_profiles"
        verbose_name = "charging profiles"
        verbose_name_plural = "charging profiles"


class Configuration(models.Model):
    key = models.TextField()
    value = models.TextField()
    readonly = models.BooleanField(null=True, blank=True)
    identity = models.TextField(null=True, blank=True)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    charge_point = models.ForeignKey("ChargePointV16", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+", db_column="charge_point_id", null=True, blank=True)

    class Meta:
        managed = False
        db_table = "configurations_v16"
        verbose_name = "configurations v16"
        verbose_name_plural = "configurations v16"


class ConnectorV16(models.Model):
    index = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=14, choices=[("available", "available"), ("preparing", "preparing"), ("charging", "charging"), ("suspended_evse", "suspended_evse"), ("suspended_ev", "suspended_ev"), ("finishing", "finishing"), ("reserved", "reserved"), ("unavailable", "unavailable"), ("faulted", "faulted")])
    connected = models.BooleanField()
    error_code = models.CharField(max_length=22, choices=[("connector_lock_failure", "connector_lock_failure"), ("ev_communication_error", "ev_communication_error"), ("ground_failure", "ground_failure"), ("high_temperature", "high_temperature"), ("internal_error", "internal_error"), ("local_list_conflict", "local_list_conflict"), ("no_error", "no_error"), ("other_error", "other_error"), ("over_current_failure", "over_current_failure"), ("over_voltage", "over_voltage"), ("power_meter_failure", "power_meter_failure"), ("power_switch_failure", "power_switch_failure"), ("reader_failure", "reader_failure"), ("reset_failure", "reset_failure"), ("under_voltage", "under_voltage"), ("weak_signal", "weak_signal")], null=True, blank=True)
    availability = models.CharField(max_length=11, choices=[("inoperative", "inoperative"), ("operative", "operative")])
    socket_type = models.TextField(null=True, blank=True)
    current_type = models.TextField(null=True, blank=True)
    connector_type = models.CharField(max_length=21, choices=[("CHADEMO", "CHADEMO"), ("DOMESTIC_A", "DOMESTIC_A"), ("DOMESTIC_B", "DOMESTIC_B"), ("DOMESTIC_C", "DOMESTIC_C"), ("DOMESTIC_D", "DOMESTIC_D"), ("DOMESTIC_E", "DOMESTIC_E"), ("DOMESTIC_F", "DOMESTIC_F"), ("DOMESTIC_G", "DOMESTIC_G"), ("DOMESTIC_H", "DOMESTIC_H"), ("DOMESTIC_I", "DOMESTIC_I"), ("DOMESTIC_J", "DOMESTIC_J"), ("DOMESTIC_K", "DOMESTIC_K"), ("DOMESTIC_L", "DOMESTIC_L"), ("IEC_60309_2_SINGLE_16", "IEC_60309_2_SINGLE_16"), ("IEC_60309_2_THREE_16", "IEC_60309_2_THREE_16"), ("IEC_60309_2_THREE_32", "IEC_60309_2_THREE_32"), ("IEC_60309_2_THREE_64", "IEC_60309_2_THREE_64"), ("IEC_62196_T1", "IEC_62196_T1"), ("IEC_62196_T1_COMBO", "IEC_62196_T1_COMBO"), ("IEC_62196_T2", "IEC_62196_T2"), ("IEC_62196_T2_COMBO", "IEC_62196_T2_COMBO"), ("IEC_62196_T3A", "IEC_62196_T3A"), ("IEC_62196_T3C", "IEC_62196_T3C"), ("TESLA_R", "TESLA_R"), ("TESLA_S", "TESLA_S")], null=True, blank=True)
    format = models.CharField(max_length=6, choices=[("SOCKET", "SOCKET"), ("CABLE", "CABLE")], null=True, blank=True)
    voltage = models.IntegerField(null=True, blank=True)
    amperage = models.IntegerField(null=True, blank=True)
    power_type = models.CharField(max_length=10, choices=[("AC_1_PHASE", "AC_1_PHASE"), ("AC_3_PHASE", "AC_3_PHASE"), ("DC", "DC")], null=True, blank=True)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    charge_point = models.ForeignKey("ChargePointV16", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+", db_column="charge_point_id", null=True, blank=True)
    evse_id = models.IntegerField(null=True, blank=True)
    last_suspended_ev = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "connectors_v16"
        verbose_name = "connectors v16"
        verbose_name_plural = "connectors v16"


class ConnectorV201(models.Model):
    index = models.IntegerField()
    evse = models.IntegerField()
    status = models.TextField(null=True, blank=True)
    updated_at = models.DateTimeField()
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)

    class Meta:
        managed = False
        db_table = "connector_v201"
        verbose_name = "connector v201"
        verbose_name_plural = "connector v201"


class DataTransfer(models.Model):
    id_token = models.TextField()
    identity = models.TextField()
    status = models.CharField(max_length=7, choices=[("valid", "valid"), ("expired", "expired"), ("invalid", "invalid")], null=True, blank=True)
    data = fields.JSONField(null=True, blank=True)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "data_transfer"
        verbose_name = "data transfer"
        verbose_name_plural = "data transfer"


class Evse(models.Model):
    index = models.IntegerField()
    identity = models.TextField()
    connector_id = models.UUIDField(null=True, blank=True)
    id = models.AutoField(primary_key=True)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    charge_point = models.ForeignKey("ChargePointV16", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+", db_column="charge_point_id", null=True, blank=True)

    class Meta:
        managed = False
        db_table = "evses"
        verbose_name = "evses"
        verbose_name_plural = "evses"


class EvseV201(models.Model):
    evse = models.TextField()
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)

    class Meta:
        managed = False
        db_table = "evse_v201"
        verbose_name = "evse v201"
        verbose_name_plural = "evse v201"


class Family(models.Model):
    name = models.TextField()
    customer = models.TextField()
    description = models.TextField(null=True, blank=True)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "families"
        verbose_name = "families"
        verbose_name_plural = "families"


class FirmwareV16(models.Model):
    request_id = models.IntegerField(null=True, blank=True)
    location = models.TextField(null=True, blank=True)
    retries = models.IntegerField(null=True, blank=True)
    retry_interval = models.IntegerField(null=True, blank=True)
    retrieve_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=27, choices=[("downloaded", "downloaded"), ("download_failed", "download_failed"), ("downloading", "downloading"), ("idle", "idle"), ("installation_failed", "installation_failed"), ("installing", "installing"), ("installed", "installed"), ("download_scheduled", "download_scheduled"), ("download_paused", "download_paused"), ("install_rebooting", "install_rebooting"), ("install_scheduled", "install_scheduled"), ("install_verification_failed", "install_verification_failed"), ("invalid_signature", "invalid_signature"), ("signature_verified", "signature_verified")], null=True, blank=True)
    firmware_version = models.TextField(null=True, blank=True)
    install_date = models.DateTimeField(null=True, blank=True)
    request = models.CharField(max_length=22, choices=[("update_firmware", "update_firmware"), ("signed_update_firmware", "signed_update_firmware")], null=True, blank=True)
    signature = models.TextField(null=True, blank=True)
    signing_certificate = models.TextField(null=True, blank=True)
    job_id = models.UUIDField(null=True, blank=True)
    requested_by = models.TextField(null=True, blank=True)
    previous_version = models.TextField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    charge_point = models.ForeignKey("ChargePointV16", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+", db_column="charge_point_id", null=True, blank=True)

    class Meta:
        managed = False
        db_table = "firmwares_v16"
        verbose_name = "firmwares v16"
        verbose_name_plural = "firmwares v16"


class FirmwareV201(models.Model):
    version = models.TextField()
    location = models.TextField()
    retrieve_date_time = models.TextField()
    request_id = models.IntegerField()
    retries = models.IntegerField(null=True, blank=True)
    status = models.TextField(null=True, blank=True)
    last_update = models.DateTimeField(null=True, blank=True)
    install_date_time = models.TextField(null=True, blank=True)
    signing_certificate = models.TextField(null=True, blank=True)
    signature = models.TextField(null=True, blank=True)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)

    class Meta:
        managed = False
        db_table = "Firmware_v201"
        verbose_name = "Firmware v201"
        verbose_name_plural = "Firmware v201"


class Incident(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    started_at = models.DateTimeField(null=True, blank=True)
    event = models.CharField(max_length=12, choices=[("connected", "connected"), ("disconnected", "disconnected"), ("faulted", "faulted"), ("unavailable", "unavailable")])
    identity = models.TextField()
    evse_id = models.IntegerField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "incidents"
        verbose_name = "incidents"
        verbose_name_plural = "incidents"


class Job(models.Model):
    status = models.CharField(max_length=11, choices=[("IN_PROGRESS", "IN_PROGRESS"), ("PENDING", "PENDING"), ("DONE", "DONE"), ("FAILED", "FAILED")])
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    event_type = models.CharField(max_length=23, choices=[("ReserveNow", "ReserveNow"), ("CancelReservation", "CancelReservation"), ("ReservationStatusUpdate", "ReservationStatusUpdate"), ("RESERVATION_CREATED", "RESERVATION_CREATED"), ("QUEUE_JOINED", "QUEUE_JOINED"), ("QUEUE_LEFT", "QUEUE_LEFT"), ("QUEUE_PROCESSED", "QUEUE_PROCESSED"), ("QUEUE_POSITION_CHANGED", "QUEUE_POSITION_CHANGED"), ("RemoteStopTransaction", "RemoteStopTransaction"), ("RemoteStartTransaction", "RemoteStartTransaction"), ("Reset", "Reset"), ("Heartbeat", "Heartbeat"), ("ChangeAvailability", "ChangeAvailability"), ("UnlockConnector", "UnlockConnector"), ("TriggerMessage", "TriggerMessage"), ("ExtendedTriggerMessage", "ExtendedTriggerMessage"), ("UpdateFirmware", "UpdateFirmware"), ("SignedUpdateFirmware", "SignedUpdateFirmware"), ("GetDiagnostics", "GetDiagnostics"), ("GetLogs", "GetLogs"), ("GetConfiguration", "GetConfiguration"), ("ChangeConfiguration", "ChangeConfiguration"), ("SendLocalList", "SendLocalList"), ("GetLocalListVersion", "GetLocalListVersion"), ("ClearCache", "ClearCache"), ("NewChargePoint", "NewChargePoint"), ("StatusNotification", "StatusNotification"), ("MeterValues", "MeterValues"), ("NewTransaction", "NewTransaction"), ("UpdateTransaction", "UpdateTransaction"), ("StopTransaction", "StopTransaction"), ("UpdateSession", "UpdateSession"), ("UpdateCdr", "UpdateCdr"), ("SetChargingProfile", "SetChargingProfile"), ("ClearChargingProfile", "ClearChargingProfile"), ("GetCompositeSchedule", "GetCompositeSchedule")], null=True, blank=True)
    request = fields.JSONField(null=True, blank=True)
    response = fields.JSONField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "jobs"
        verbose_name = "jobs"
        verbose_name_plural = "jobs"


class LocalRfid(models.Model):
    id_token = models.TextField()
    identity = models.TextField()
    list_version = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=13, choices=[("accepted", "accepted"), ("blocked", "blocked"), ("expired", "expired"), ("invalid", "invalid"), ("concurrent_tx", "concurrent_tx")])
    expiry_date = models.DateTimeField(null=True, blank=True)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "local_rfids"
        verbose_name = "local rfids"
        verbose_name_plural = "local rfids"


class Location(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=45)
    postal_code = models.CharField(max_length=10, null=True, blank=True)
    city = models.CharField(max_length=45)
    country = models.CharField(max_length=3)
    location_type = models.CharField(max_length=18, choices=[("ON_STREET", "ON_STREET"), ("PARKING_GARAGE", "PARKING_GARAGE"), ("UNDERGROUND_GARAGE", "UNDERGROUND_GARAGE"), ("PARKING_LOT", "PARKING_LOT"), ("OTHER", "OTHER"), ("UNKNOWN", "UNKNOWN")])
    coordinates = fields.JSONField(null=True, blank=True)
    operator = fields.JSONField(null=True, blank=True)
    related_locations = fields.JSONField(null=True, blank=True)
    opening_times = fields.JSONField(null=True, blank=True)
    suboperator = fields.JSONField(null=True, blank=True)
    owner = fields.JSONField(null=True, blank=True)
    charger_type = models.CharField(max_length=7, choices=[("PRIVATE", "PRIVATE"), ("PUBLIC", "PUBLIC"), ("ROAMING", "ROAMING")])
    work_place = models.CharField(max_length=20, choices=[("CAPTIVE_FLEET", "CAPTIVE_FLEET"), ("PUBLIC", "PUBLIC"), ("EMPLOYEES", "EMPLOYEES"), ("HEAVY_TRANSPORTATION", "HEAVY_TRANSPORTATION"), ("WORKPLACE", "WORKPLACE")])
    client = models.CharField(max_length=255)
    refund_price = fields.JSONField(null=True, blank=True)
    tax_basis_price = models.FloatField(null=True, blank=True)
    owner_email = models.TextField(null=True, blank=True)
    max_power = models.FloatField(null=True, blank=True)
    sync_ocpi = models.BooleanField()
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    last_updated = models.DateTimeField(null=True, blank=True)
    time_zone = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "locations"
        verbose_name = "locations"
        verbose_name_plural = "locations"


class LogV16(models.Model):
    log_type = models.TextField(null=True, blank=True)
    request_id = models.IntegerField(null=True, blank=True)
    location = models.TextField(null=True, blank=True)
    retries = models.IntegerField(null=True, blank=True)
    retry_interval = models.IntegerField(null=True, blank=True)
    start_time = models.TextField(null=True, blank=True)
    stop_time = models.TextField(null=True, blank=True)
    file_name = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=23, choices=[("bad_message", "bad_message"), ("idle", "idle"), ("not_supported_operation", "not_supported_operation"), ("permission_denied", "permission_denied"), ("uploaded", "uploaded"), ("upload_failure", "upload_failure"), ("uploading", "uploading")], null=True, blank=True)
    job_id = models.UUIDField(null=True, blank=True)
    requested_by = models.TextField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    charge_point = models.ForeignKey("ChargePointV16", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+", db_column="charge_point_id", null=True, blank=True)

    class Meta:
        managed = False
        db_table = "logs_v16"
        verbose_name = "logs v16"
        verbose_name_plural = "logs v16"


class LogV201(models.Model):
    type = models.TextField()
    location = models.TextField()
    request_id = models.IntegerField()
    from_date = models.DateTimeField(null=True, blank=True)
    to_date = models.DateTimeField(null=True, blank=True)
    retries = models.IntegerField(null=True, blank=True)
    status = models.TextField(null=True, blank=True)
    last_update = models.DateTimeField(null=True, blank=True)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)

    class Meta:
        managed = False
        db_table = "log_v201"
        verbose_name = "log v201"
        verbose_name_plural = "log v201"


class Maintenance(models.Model):
    reason = models.TextField(null=True, blank=True)
    maintainer = models.TextField(null=True, blank=True)
    identity = models.TextField(null=True, blank=True)
    maintenance_at = models.DateTimeField()
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "maintenances"
        verbose_name = "maintenances"
        verbose_name_plural = "maintenances"


class MeterValue(models.Model):
    timestamp = models.DateTimeField(null=True, blank=True)
    measurand = models.TextField(null=True, blank=True)
    context = models.TextField(null=True, blank=True)
    phase_type = models.TextField(null=True, blank=True)
    unit = models.TextField(null=True, blank=True)
    value = models.FloatField()
    location = models.TextField(null=True, blank=True)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    transaction = models.ForeignKey("TransactionV16", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+", db_column="transaction_id")

    class Meta:
        managed = False
        db_table = "meter_values_v16"
        verbose_name = "meter values v16"
        verbose_name_plural = "meter values v16"


class PendingDoubleAuth(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    identity = models.TextField()
    vehicle_id_tag = models.TextField()
    vehicle_ref = models.TextField()
    status = models.CharField(max_length=8, choices=[("PENDING", "PENDING"), ("CONSUMED", "CONSUMED"), ("USED", "USED")])
    expires_at = models.DateTimeField()
    user_id_token = models.TextField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "pending_double_auths"
        verbose_name = "pending double auths"
        verbose_name_plural = "pending double auths"


class PowerMetric(models.Model):
    transaction_id = models.IntegerField()
    identity = models.TextField()
    connector_index = models.IntegerField()
    timestamp = models.DateTimeField(null=True, blank=True)
    energy_kwh = models.FloatField(null=True, blank=True)
    energy_delivered_wh = models.FloatField(null=True, blank=True)
    power_kw = models.FloatField(null=True, blank=True)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)

    class Meta:
        managed = False
        db_table = "power_metrics"
        verbose_name = "power metrics"
        verbose_name_plural = "power metrics"


class QueueGroupMember(models.Model):
    user_email = models.TextField(null=True, blank=True)
    is_group_leader = models.BooleanField()
    joined_at = models.DateTimeField(null=True, blank=True)
    id = models.BigAutoField(primary_key=True)
    queue = models.ForeignKey("ReservationQueue", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+", db_column="queue_id")
    rfid = models.ForeignKey("Rfid", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+", db_column="rfid_id")
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "queue_group_members"
        verbose_name = "queue group members"
        verbose_name_plural = "queue group members"


class RejectedRfid(models.Model):
    identity = models.TextField(null=True, blank=True)
    reason = models.TextField(null=True, blank=True)
    reason_kind = models.CharField(max_length=28, choices=[("UNKNOWN", "UNKNOWN"), ("RFID_DOES_NOT_EXIST", "RFID_DOES_NOT_EXIST"), ("RFID_NOT_ACCEPTED", "RFID_NOT_ACCEPTED"), ("PAYMENT_REJECTED", "PAYMENT_REJECTED"), ("PRIVATE_CHARGER", "PRIVATE_CHARGER"), ("EMSP_REJECTION", "EMSP_REJECTION"), ("NO_AVAILABLE_CONNECTOR", "NO_AVAILABLE_CONNECTOR"), ("DOUBLE_AUTH_VEHICLE_REQUIRED", "DOUBLE_AUTH_VEHICLE_REQUIRED"), ("DOUBLE_AUTH_EXPIRED", "DOUBLE_AUTH_EXPIRED"), ("DOUBLE_AUTH_PAIR_REJECTED", "DOUBLE_AUTH_PAIR_REJECTED")])
    rfid_customer = models.TextField(null=True, blank=True)
    charger_customer = models.TextField(null=True, blank=True)
    charger_type = models.TextField(null=True, blank=True)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    id_token = models.TextField()
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "rejected_rfids"
        verbose_name = "rejected rfids"
        verbose_name_plural = "rejected rfids"


class Reservation(models.Model):
    id_tag = models.TextField()
    expiry_date = models.DateTimeField(null=True, blank=True)
    parent_id_tag = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=11, choices=[("accepted", "accepted"), ("faulted", "faulted"), ("occupied", "occupied"), ("rejected", "rejected"), ("unavailable", "unavailable")], null=True, blank=True)
    cancel_reservation = models.BooleanField(null=True, blank=True)
    confirmation = models.BooleanField()
    email = models.TextField(null=True, blank=True)
    id = models.BigAutoField(primary_key=True)
    evse = models.ForeignKey("Evse", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+", db_column="evse_id")
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    rfid = models.ForeignKey("Rfid", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+", db_column="rfid_id")

    class Meta:
        managed = False
        db_table = "reservations_v16"
        verbose_name = "reservations v16"
        verbose_name_plural = "reservations v16"


class ReservationQueue(models.Model):
    position = models.IntegerField()
    joined_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    notification_sent = models.BooleanField()
    group_type = models.CharField(max_length=8, choices=[("adhoc", "adhoc"), ("family", "family"), ("customer", "customer")])
    id = models.BigAutoField(primary_key=True)
    group_id = models.UUIDField()
    evse = models.ForeignKey("Evse", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+", db_column="evse_id")
    group_leader_rfid = models.ForeignKey("Rfid", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+", db_column="group_leader_rfid_id")
    status = models.CharField(max_length=10, choices=[("waiting", "waiting"), ("processing", "processing"), ("expired", "expired"), ("cancelled", "cancelled")])
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "reservation_queues"
        verbose_name = "reservation queues"
        verbose_name_plural = "reservation queues"


class Rfid(models.Model):
    expiry_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=13, choices=[("accepted", "accepted"), ("blocked", "blocked"), ("expired", "expired"), ("invalid", "invalid"), ("concurrent_tx", "concurrent_tx")])
    parent_id_tag = models.TextField(null=True, blank=True)
    email = models.TextField()
    full_name = models.TextField(null=True, blank=True)
    first_name = models.TextField(null=True, blank=True)
    last_name = models.TextField(null=True, blank=True)
    customer = models.TextField(null=True, blank=True)
    label = models.TextField(null=True, blank=True)
    family = models.TextField()
    priority_level = models.IntegerField()
    type = models.CharField(max_length=13, choices=[("RFID", "RFID"), ("MacAddress", "MacAddress"), ("MAC_ADDRESS", "MAC_ADDRESS"), ("VirtualRfid", "VirtualRfid"), ("PlugAndCharge", "PlugAndCharge"), ("Other", "Other")])
    holder_type = models.CharField(max_length=7, choices=[("USER", "USER"), ("VEHICLE", "VEHICLE")])
    roaming = models.BooleanField()
    whitelist = models.BooleanField()
    extra_info = fields.JSONField(null=True, blank=True)
    id = models.AutoField(primary_key=True)
    id_token = models.TextField(unique=True)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    user = models.ForeignKey("User", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+", db_column="user_id", null=True, blank=True)
    vip_config = models.ForeignKey("VipConfig", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+", db_column="vip_config_id", null=True, blank=True)

    class Meta:
        managed = False
        db_table = "rfids"
        verbose_name = "rfids"
        verbose_name_plural = "rfids"


class Tariff(models.Model):
    name = models.TextField(null=True, blank=True)
    currency = models.TextField()
    customer = models.TextField(null=True, blank=True)
    family = models.TextField(null=True, blank=True)
    type = models.CharField(max_length=7, choices=[("DEFAULT", "DEFAULT"), ("CUSTOM", "CUSTOM"), ("ROAMING", "ROAMING")], null=True, blank=True)
    elements = fields.JSONField(null=True, blank=True)
    tariff_alt_text = fields.JSONField(null=True, blank=True)
    tariff_alt_url = models.TextField(null=True, blank=True)
    tax_included = models.BooleanField(null=True, blank=True)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    last_updated = models.DateTimeField(null=True, blank=True)
    created_by = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "tariffs"
        verbose_name = "tariffs"
        verbose_name_plural = "tariffs"


class TransactionV16(models.Model):
    timestamp = models.TextField()
    email = models.TextField(null=True, blank=True)
    reservation_id = models.IntegerField(null=True, blank=True)
    id_tag = models.TextField(null=True, blank=True)
    vehicle_id_tag = models.TextField(null=True, blank=True)
    connector_index = models.IntegerField(null=True, blank=True)
    evse_id = models.IntegerField(null=True, blank=True)
    reason = models.CharField(max_length=15, choices=[("emergency_stop", "emergency_stop"), ("ev_disconnected", "ev_disconnected"), ("hard_reset", "hard_reset"), ("local", "local"), ("other", "other"), ("power_loss", "power_loss"), ("reboot", "reboot"), ("remote", "remote"), ("soft_reset", "soft_reset"), ("unlock_command", "unlock_command"), ("de_authorized", "de_authorized")], null=True, blank=True)
    meter_start = models.FloatField(null=True, blank=True)
    meter_end = models.FloatField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    energy_delivered = models.FloatField(null=True, blank=True)
    active_duration = models.FloatField(null=True, blank=True)
    overall_duration = models.FloatField(null=True, blank=True)
    battery_percentage = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=8, choices=[("PENDING", "PENDING"), ("ONGOING", "ONGOING"), ("FINISHED", "FINISHED"), ("FAILED", "FAILED")])
    authorization_id = models.TextField(null=True, blank=True)
    authorization_status = models.CharField(max_length=13, choices=[("accepted", "accepted"), ("blocked", "blocked"), ("expired", "expired"), ("invalid", "invalid"), ("concurrent_tx", "concurrent_tx")], null=True, blank=True)
    authorization_reference = models.TextField(null=True, blank=True)
    provider = models.CharField(max_length=19, choices=[("SWISH", "SWISH"), ("GIREVE", "GIREVE"), ("GETAWAY", "GETAWAY"), ("MOBILE_B2C_APP", "MOBILE_B2C_APP"), ("MOBILE_B2B_APP", "MOBILE_B2B_APP"), ("INTERFACE_PLATTFORM", "INTERFACE_PLATTFORM"), ("OTHER", "OTHER")], null=True, blank=True)
    location_id = models.TextField(null=True, blank=True)
    token_uid = models.TextField(null=True, blank=True)
    tariff_id = models.UUIDField(null=True, blank=True)
    total_cost = models.FloatField(null=True, blank=True)
    total_parking_time = models.FloatField(null=True, blank=True)
    charging_periods = fields.JSONField(null=True, blank=True)
    work_place = models.CharField(max_length=20, choices=[("CAPTIVE_FLEET", "CAPTIVE_FLEET"), ("PUBLIC", "PUBLIC"), ("EMPLOYEES", "EMPLOYEES"), ("HEAVY_TRANSPORTATION", "HEAVY_TRANSPORTATION"), ("WORKPLACE", "WORKPLACE")])
    refund_price = fields.JSONField(null=True, blank=True)
    cost_details = fields.JSONField(null=True, blank=True)
    tax_basis_price = models.FloatField(null=True, blank=True)
    mileage = models.IntegerField(null=True, blank=True)
    time_zone = models.TextField(null=True, blank=True)
    tariffs = fields.JSONField(null=True, blank=True)
    uid = models.UUIDField(unique=True)
    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    last_session_push_at = models.DateTimeField(null=True, blank=True)
    refund = models.FloatField(null=True, blank=True)
    billing_to_company = models.FloatField(null=True, blank=True)
    charging_limits = fields.JSONField(null=True, blank=True)
    mission_description = models.TextField(null=True, blank=True)
    connector = models.ForeignKey("ConnectorV16", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+", db_column="connector_id", null=True, blank=True)
    rfid = models.ForeignKey("Rfid", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+", db_column="rfid_id", null=True, blank=True)

    class Meta:
        managed = False
        db_table = "transactions_v16"
        verbose_name = "transactions v16"
        verbose_name_plural = "transactions v16"


class TransactionV201(models.Model):
    start_time = models.DateTimeField()
    stop_time = models.DateTimeField(null=True, blank=True)
    meter = models.FloatField()
    charging_duration = models.FloatField(null=True, blank=True)
    extra_charging_duration = models.FloatField(null=True, blank=True)
    stop_reason = models.TextField(null=True, blank=True)
    last_update = models.DateTimeField()
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)

    class Meta:
        managed = False
        db_table = "transaction_v201"
        verbose_name = "transaction v201"
        verbose_name_plural = "transaction v201"


class User(models.Model):
    email = models.TextField()
    family = models.TextField(null=True, blank=True)
    phone = models.TextField(null=True, blank=True)
    full_name = models.TextField(null=True, blank=True)
    receive_email = models.BooleanField()
    receive_sms = models.BooleanField()
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "users"
        verbose_name = "users"
        verbose_name_plural = "users"


class VipConfig(models.Model):
    name = models.TextField()
    description = models.TextField(null=True, blank=True)
    charging_profile_template = models.CharField(max_length=15, choices=[("MAX_POWER", "MAX_POWER"), ("FAST_CHARGING", "FAST_CHARGING"), ("MEDIUM_CHARGING", "MEDIUM_CHARGING"), ("ECO_CHARGING", "ECO_CHARGING"), ("CUSTOM", "CUSTOM")])
    max_power_watts = models.IntegerField()
    custom_charging_profile = fields.JSONField(null=True, blank=True)
    is_active = models.BooleanField()
    override_scheduled_profiles = models.BooleanField()
    enable_load_balancing = models.BooleanField()
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_to = models.DateTimeField(null=True, blank=True)
    id = models.AutoField(primary_key=True)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "vip_configs"
        verbose_name = "vip configs"
        verbose_name_plural = "vip configs"
