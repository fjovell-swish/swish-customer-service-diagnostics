# The diagnostics page on :8000 (PORT): gunicorn + WhiteNoise via deploy/entrypoints/web.sh.
# Non-root (uid 1000), runtime dependencies only, hashed lockfile.
FROM python:3.15-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN groupadd --gid 1000 app && useradd --uid 1000 --gid app --create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY requirements.txt .
RUN pip install --require-hashes -r requirements.txt
COPY --chown=app:app manage.py pyproject.toml ./
COPY --chown=app:app deploy/entrypoints ./deploy/entrypoints
COPY --chown=app:app config ./config
COPY --chown=app:app diagnostics ./diagnostics
COPY --chown=app:app services ./services
RUN mkdir -p /app/staticfiles && chown app:app /app/staticfiles
USER app
# Placeholders: collectstatic only needs the settings to import; no real secret is baked in.
RUN SECRET_KEY=build DJANGO_ALLOWED_HOSTS=x AUTH_PROXY_SECRET=build DATABASE_URL=postgres://x/x \
    OCPP_DATABASE_URL=postgres://x/x \
    OCPP_TENANTS=public python manage.py collectstatic --noinput --settings config.settings.production
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/healthz')" || exit 1
ENTRYPOINT ["/app/deploy/entrypoints/web.sh"]
