from typing import Any

from services.admin_registration import register_app_models

# Per-model admin options layered over the generated defaults, keyed by model class name.
OVERRIDES: dict[str, dict[str, Any]] = {}

register_app_models("ocpp", overrides=OVERRIDES)
