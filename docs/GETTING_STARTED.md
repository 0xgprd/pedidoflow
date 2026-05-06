# Getting Started — desarrollo local

## 1. Pre-requisitos

| Tool | Versión | Comprobación |
|------|---------|--------------|
| Docker Desktop | 4.x+ | `docker --version` |
| Python | 3.11+ | `python --version` |
| Node | 20+ | `node --version` |
| pnpm | 9+ | `npm i -g pnpm && pnpm -v` |
| Git | reciente | `git --version` |

## 2. Clonar y configurar

```bash
cd "C:\Users\gperd\Desktop\Proyectos VS Code\pedidoflow"
copy .env.example .env       # luego rellenar credenciales reales (cuando las tengamos)
```

## 3. Levantar servicios (Postgres + Redis)

```bash
docker compose up -d
docker compose ps           # ambos deben estar "healthy"
```

Conexión Postgres: `postgresql://pedidoflow:pedidoflow@localhost:5432/pedidoflow`

Tools opcionales:
```bash
docker compose --profile tools up -d   # incluye Adminer en :8080
```

## 4. Backend (FastAPI)

```bash
cd apps/api
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

- API: http://localhost:8000
- Docs (OpenAPI/Swagger): http://localhost:8000/docs
- Health: http://localhost:8000/api/v1/health
- Ready (DB + pgvector): http://localhost:8000/api/v1/health/ready

Tests:
```bash
pytest
```

## 5. Frontend (React)

```bash
cd apps/web
pnpm install
pnpm dev
```

Web: http://localhost:5173 — debe mostrar el estado del backend en la página de inicio.

## 6. Worker Celery (cuando haya tasks — Fase 1+)

```bash
cd apps/api
celery -A app.workers.celery_app worker --loglevel=info
```

## 7. Comandos útiles

```bash
# Apagar todo
docker compose down

# Reset DB completo (⚠ borra datos)
docker compose down -v

# Logs Postgres
docker compose logs -f postgres
```

## Troubleshooting

- **`pgvector` no encontrado**: comprueba que estás usando `pgvector/pgvector:pg16` (no `postgres:16`).
  Reset volumen: `docker compose down -v && docker compose up -d`.
- **CORS errors en frontend**: el dev server de Vite proxea `/api/*` automáticamente. Si llamas
  con `fetch('http://localhost:8000/...')` directo, asegúrate de que `cors_origins` incluye `http://localhost:5173`.
- **`init_db` falla en startup**: ¿Postgres listo? `docker compose ps`. La app no debe crashear, solo loguea warning.
