# Backend Order Flow — imagen Python para Railway/Docker.
# Railway prefiere este Dockerfile sobre Nixpacks cuando ambos existen.
# rebuild-trigger: 2026-05-07-fix-config-parents

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Deps de sistema (libpq para psycopg, gcc para wheels nativos, curl para healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Metadata del paquete + README primero (cache de Docker para cambios de código)
COPY pyproject.toml README.md ./

# Install no-editable para evitar "metadata-generation-failed" del editable mode.
RUN pip install --upgrade pip setuptools wheel \
    && pip install .

# Código + migraciones
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

# Railway inyecta $PORT. Arranca uvicorn directamente — las migraciones Alembic
# se aplican manualmente via MCP Supabase (la baseline + índices ya están en DB).
# Si añades una nueva migración: aplícala a Supabase ANTES de hacer push aquí.
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'
