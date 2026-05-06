# Getting Started — desarrollo local

## 1. Pre-requisitos

| Tool | Versión | Estado en este equipo (2026-05-06) |
|------|---------|------------------------------------|
| Python | 3.12 | ✅ instalado (`py -3.12`) |
| Node | 20+ | ✅ v24.13.1 |
| pnpm | 9+ | ✅ 10.33.4 |
| Git | reciente | ✅ 2.53 |
| Docker Desktop | 4.x+ | ❌ **falta instalar** |

> ⚠️ **Docker no está instalado**. Sin él no funciona Postgres ni Redis local.
> Descargar: https://www.docker.com/products/docker-desktop/ (Windows, ~600 MB).
> Mientras tanto, los tests Python pasan (usan SQLite en memoria) y el frontend
> compila sin problema, pero el backend no podrá conectar a la DB.
>
> **Workaround temporal sin Docker**: instalar Postgres 16 nativo + extensión pgvector,
> o usar un Postgres cloud (Supabase free tier, Neon, Railway). Para el MVP
> es preferible Docker — instalar antes de Fase 1.

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

> **Ya está bootstrapped en este equipo** (venv creado en `apps/api/.venv` con Python 3.12 + 100+ deps instaladas y tests pasando 4/4).

Para ejecutar (cada vez que retomes trabajo):
```bash
cd apps/api
.venv\Scripts\activate
uvicorn app.main:app --reload
```

Setup desde cero (otro equipo):
```bash
cd apps/api
py -3.12 -m venv .venv      # o python -m venv .venv si la default es 3.11/3.12
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

> **Ya está bootstrapped en este equipo** (`node_modules` instalado, build verificado: 193 KB JS).

Para ejecutar:
```bash
cd apps/web
pnpm dev
```

Setup desde cero (otro equipo):
```bash
cd apps/web
pnpm install     # o `npm install` si no tienes pnpm
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
