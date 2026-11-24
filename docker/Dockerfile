# syntax=docker/dockerfile:1
# The diagnostics app's one image. docker/entrypoint.sh runs the role it's given:
#
#   web (the default)   gunicorn + WhiteNoise on $PORT (8000): the Container App
#   migrate             manage.py migrate: the migrate job, before each rollout
#   manage <command>    any manage.py command, e.g. `manage check --deploy`
#
#   docker build -f docker/Dockerfile -t swishdiag-web .
#
# Two stages: `dependencies` installs the hashed lockfile into a virtualenv, `runtime` copies
# that virtualenv and the app's code, owned by root and read-only to the app user (uid 1000).
ARG PYTHON_VERSION=3.15

# --- dependencies ------------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS dependencies

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN python -m venv /opt/venv
# Runtime dependencies only (the test extra never gets here), each one pinned with its hashes.
RUN --mount=type=bind,source=requirements.txt,target=/tmp/requirements.txt \
    --mount=type=cache,target=/root/.cache/pip \
    /opt/venv/bin/pip install --require-hashes -r /tmp/requirements.txt

# --- runtime -----------------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

LABEL org.opencontainers.image.title="swish-customer-service-diagnostics" \
      org.opencontainers.image.description="Charger diagnostics for Swish customer support"

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --home-dir /app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=dependencies /opt/venv /opt/venv
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY docker/healthcheck.py /usr/local/bin/healthcheck
COPY manage.py ./
COPY config ./config
COPY deployments ./deployments
COPY mcp_api ./mcp_api
COPY diagnostics ./diagnostics
COPY services ./services
COPY templates ./templates

# Still root: the static files and the bytecode are written now, so nothing in /app has to be
# writable at runtime. collectstatic only needs the production settings to import: the values are
# placeholders, no secret is baked in.
RUN SECRET_KEY=build DJANGO_ALLOWED_HOSTS=build \
    DATABASE_URL=postgres://build/build OCPP_DATABASE_URL=postgres://build/build \
    OCPP_TENANTS=public \
    python manage.py collectstatic --noinput --settings config.settings.production \
    && python -m compileall -q /app

# Numeric, so platforms that require a non-root user (runAsNonRoot) can check it.
USER 1000:1000

EXPOSE 8000
# Container Apps probes /healthz itself; this one is for docker run and compose.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD ["healthcheck"]
ENTRYPOINT ["entrypoint.sh"]
CMD ["web"]
