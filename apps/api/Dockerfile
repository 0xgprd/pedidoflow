# Backend Order Flow — imagen Python para Railway/Docker.
# Railway prefiere este Dockerfile sobre Nixpacks cuando ambos existen.

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

# Healthcheck (Railway lo usa para saber si el servicio está vivo)
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://localhost:${PORT:-8080}/api/v1/health" || exit 1

# Railway inyecta $PORT. Aplicamos migraciones antes de arrancar.
# Usar shell form para que $PORT se expanda correctamente.
CMD alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'
