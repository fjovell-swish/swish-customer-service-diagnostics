import os

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("OCPP_DATABASE_URL", "postgres://unused@localhost/ocpp")
os.environ.setdefault("OCPP_TENANTS", "public,eosgie")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from config.settings import *  # noqa: E402, F401, F403

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
