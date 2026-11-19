"""
GitHub Actions: local settings with DEBUG off and the Postgres service the CI workflow starts
(.github/workflows/ci.yaml, swish-charge/ci-workflows' python-tests.yml), hard-coded to the same
values. Selected with DJANGO_SETTINGS_MODULE=config.settings.ci in the workflow. Locally, tests run
on SQLite (config.settings.local).

The api-ocpp aliases are writable here: tests create api-ocpp's tables in each tenant's test
database.
"""

from config.settings.local import OCPP_TENANTS
from config.settings.local import *  # noqa: F401,F403
from config.settings.local import ocpp_databases

DEBUG = False
SECRET_KEY = "ci-only-not-a-secret"

POSTGRES_URL = "postgres://swish:swish@localhost:5432/swish"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "swish",
        "USER": "swish",
        "PASSWORD": "swish",
        "HOST": "localhost",
        "PORT": "5432",
    },
    **ocpp_databases(POSTGRES_URL, OCPP_TENANTS, read_only=False, test_names=True),
}
