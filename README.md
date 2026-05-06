# Pedidoflow

SaaS para automatización de pedidos en ERPs (Sage 200 first-class). PYMEs industriales españolas.

> Status: **Fase 0 - Setup** (Semana 1 de 12)

## Stack

- **Backend**: FastAPI + Python 3.11 + SQLModel + Celery + Redis
- **DB**: Postgres 16 + pgvector
- **Frontend**: React + Vite + TypeScript + Tailwind + shadcn/ui
- **Storage PDFs**: Cloudflare R2 (S3-compatible)
- **IA**: Claude Sonnet 4.6 (Anthropic) + Voyage AI embeddings
- **Auth**: Clerk
- **Hosting**: Railway

## Estructura del repo

```
pedidoflow/
├── apps/
│   ├── api/                  # FastAPI backend
│   │   ├── app/
│   │   │   ├── api/          # Routers REST
│   │   │   ├── core/         # Config, DB, security
│   │   │   ├── models/       # SQLModel entities
│   │   │   ├── services/     # Lógica negocio (extracción, lookup, Sage client)
│   │   │   └── workers/      # Celery tasks
│   │   ├── tests/
│   │   └── pyproject.toml
│   └── web/                  # React frontend
├── docker-compose.yml        # Postgres + pgvector + Redis local
├── infra/                    # Railway / deployment configs
├── scripts/                  # Migraciones, seeds, utilities
└── docs/                     # Arquitectura, decisiones, runbooks
```

## Quickstart (desarrollo local)

### Pre-requisitos
- Docker Desktop
- Python 3.11+
- Node 20+
- pnpm (`npm i -g pnpm`)

### Levantar entorno
```bash
# 1. Servicios (Postgres+pgvector + Redis)
docker compose up -d

# 2. Backend
cd apps/api
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -e ".[dev]"
uvicorn app.main:app --reload

# 3. Frontend
cd apps/web
pnpm install
pnpm dev
```

API: http://localhost:8000  |  Docs: http://localhost:8000/docs  |  Web: http://localhost:5173

## Roadmap

Ver `docs/ROADMAP.md` (12 semanas, 6 fases). Plan original en
`C:\Users\gperd\.claude\plans\tu-peux-me-dire-parallel-lagoon.md`.

## Cliente 0
Quimilock — sin coste durante MVP a cambio de feedback intensivo.
