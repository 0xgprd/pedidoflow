# Pedidoflow API

Backend FastAPI del SaaS Pedidoflow.

## Setup local

```bash
python -m venv .venv
.venv\Scripts\activate         # Windows
# source .venv/bin/activate    # macOS/Linux
pip install -e ".[dev]"
cp ../../.env.example ../../.env  # rellenar valores
uvicorn app.main:app --reload
```

API: http://localhost:8000  •  Docs (OpenAPI): http://localhost:8000/docs

## Tests

```bash
pytest
```

## Estructura

- `app/main.py` — entrypoint FastAPI
- `app/core/` — configuración, DB, seguridad
- `app/api/` — routers REST (versionados en `/api/v1/`)
- `app/models/` — entidades SQLModel
- `app/services/` — lógica de negocio
- `app/workers/` — tasks Celery (extracción IA, polling Sage, etc.)
- `tests/` — pytest
