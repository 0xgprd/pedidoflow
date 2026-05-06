# Pedidoflow — Contexto para Claude Code

## Qué es esto

SaaS multi-tenant de automatización de pedidos en ERPs (Sage 200 first-class).
Pivote estratégico desde un workflow n8n específico de Quimilock hacia un producto
vendible a PYMEs industriales españolas. Competidor directo: **mydost.ai**
(https://www.mydost.ai), partner Sage.

**Cliente 0**: Quimilock (gratis durante MVP a cambio de feedback).
**Plan estratégico completo**: `C:\Users\gperd\.claude\plans\tu-peux-me-dire-parallel-lagoon.md`
**Roadmap por fases**: `docs/ROADMAP.md` (12 semanas, 6 fases).

## Estado actual

**Fase 0 completada (semana 1)** — repo bootstrapped, deps instaladas, tests pasando.

```
pedidoflow/
├── apps/
│   ├── api/                   # FastAPI 0.136 + SQLModel 0.0.38 + Python 3.12
│   │   ├── .venv/             # ✅ creada, 100+ deps instaladas
│   │   ├── app/
│   │   │   ├── main.py        # Entrypoint, lifespan, CORS
│   │   │   ├── core/          # config (pydantic-settings), db (SQLModel), logging (structlog)
│   │   │   ├── api/           # router.py, health.py, tenants.py
│   │   │   ├── models/        # base.py, tenant.py
│   │   │   ├── services/      # vacío — fase 1+
│   │   │   └── workers/       # celery_app.py (skeleton)
│   │   ├── tests/             # ✅ 4/4 pasando (test_health, test_tenants)
│   │   └── pyproject.toml
│   └── web/                   # React 18 + Vite 5 + TS + Tailwind + shadcn
│       ├── node_modules/      # ✅ instalado con pnpm 10.33
│       ├── src/
│       │   ├── App.tsx, main.tsx, index.css
│       │   ├── components/    # Layout.tsx + ui/button.tsx (shadcn)
│       │   ├── pages/         # Home, Inbox, Catalog (placeholders)
│       │   └── lib/           # api.ts, utils.ts (cn helper)
│       └── package.json
├── docker-compose.yml         # Postgres 16 + pgvector + Redis (no levantado, falta Docker)
├── scripts/init-db.sql        # CREATE EXTENSION vector, pg_trgm, uuid-ossp
├── docs/
│   ├── ROADMAP.md             # 12 semanas, 6 fases
│   ├── ARCHITECTURE.md        # 6 ADRs + diagrama + modelo datos
│   └── GETTING_STARTED.md     # quickstart
├── .env.example               # template completo (Anthropic, Voyage, R2, Clerk, MS Graph, Sage 200)
└── README.md
```

## Stack confirmado

- **Backend**: FastAPI + SQLModel + Postgres 16 + pgvector + Celery + Redis + structlog
- **Frontend**: React 18 + Vite + TypeScript + Tailwind + shadcn/ui (style: new-york, baseColor: slate)
- **IA**: Claude Sonnet 4.6 (extracción) + Voyage AI `voyage-3` (embeddings)
- **Storage**: Cloudflare R2 (S3-compatible, sin egress fees)
- **Auth**: Clerk (placeholders en .env)
- **Email**: Microsoft Graph API
- **ERP**: Sage 200 Sales API (referencia técnica en
  `C:\Users\gperd\.claude\projects\C--Users-gperd-Desktop-Proyectos-VS-Code-Quimilock\memory\reference_sage200_api.md`)
- **Hosting**: Railway (no desplegado aún)

## Decisiones arquitectónicas (ver `docs/ARCHITECTURE.md`)

1. **Postgres + pgvector** como única DB (relacional + vectorial)
2. **FastAPI + SQLModel** (mismo equipo Pydantic)
3. **Celery + Redis** para tasks IA pesadas (extracción tarda 10-30s)
4. **Claude Sonnet 4.6** mejor que GPT-4o para tablas + caching nativo
5. **Multi-tenancy por columna** `tenant_id` (no schema-per-tenant)
6. **Cloudflare R2** sobre AWS S3 (sin egress)

## Comandos diarios

```bash
# Backend
cd apps/api
.venv\Scripts\activate
uvicorn app.main:app --reload      # http://localhost:8000/docs
pytest                             # 4 tests pasando

# Frontend
cd apps/web
pnpm dev                           # http://localhost:5173

# DB local (cuando esté Docker instalado)
docker compose up -d
docker compose --profile tools up -d   # incluye Adminer en :8080
docker compose down -v             # ⚠ borra datos

# Worker Celery (fase 1+)
cd apps/api
celery -A app.workers.celery_app worker --loglevel=info
```

## Pendientes inmediatos

1. **Instalar Docker Desktop** (https://www.docker.com/products/docker-desktop/)
   — sin él no hay Postgres ni Redis local
2. **Copiar `.env.example` a `.env`** y rellenar credenciales reales
   (al menos `ANTHROPIC_API_KEY` para empezar Fase 1)
3. **Cuenta Clerk free tier** (https://clerk.com) → coger `pk_test_` y `sk_test_`
4. **Cuenta Cloudflare R2** → bucket `pedidoflow-documents` + access keys
5. **Cuenta Voyage AI** (https://www.voyageai.com) → API key

## Próxima fase: Fase 1 — Document ingestion + extracción IA (semanas 2-3)

A implementar (orden recomendado):

1. **Modelo `Document`** (`app/models/document.py`):
   `id, tenant_id, source (upload|email), pdf_url, status (pending|extracted|approved|rejected),
   source_email, extracted_json, raw_text, created_at, processed_at`
2. **Servicio storage** (`app/services/storage.py`): cliente boto3 → R2
3. **Endpoint `POST /api/v1/documents`**: upload PDF multipart → guardar R2 → crear Document
4. **Servicio extracción** (`app/services/extraction.py`):
   port del prompt n8n "IA Extraccion Pedido" → Anthropic SDK Python
5. **Worker Celery `extract_document`**: descarga PDF → llama extracción → guarda JSON
6. **Endpoints GET**: lista + detalle Document
7. **UI**: pantalla upload + lista + detalle JSON crudo

### Conocimiento del n8n a portar (no reinventar)

Lecciones del workflow n8n actual (production en `C:\Users\gperd\Desktop\Proyectos VS Code\Quimilock`):
- **Anti-contaminación de refs** en el prompt extracción: ejemplos explícitos
  (TF-75 ≠ TF-751, GF-1 ≠ GF-11)
- **Sanitización contra catálogo** ANTES de la query (corrige typos del LLM)
- **Variant disambiguation** por descripción (T2-400 BLANC vs ROUGE)
- **Exact match priority** sobre prefix matching (T-A no es T-AT)
- **Canonical filename** para extraer número de oferta (`/TL\d{6}-\d+/`)
- **Reglas transporte**: si `total_materiel < 2500€ HT` → añadir transporte por peso

Referencias:
- Memoria n8n: `C:\Users\gperd\.claude\projects\C--Users-gperd-Desktop-Proyectos-VS-Code-Quimilock\memory\project_sage200_automation.md`
- Sage API: `...\memory\reference_sage200_api.md`
- 5 pedidos reales para tests: `...\memory\project_sage200_pedidos_analysis.md`

## Convenciones de código

### Python (apps/api)
- Type hints estrictos (mypy strict, ruff lint)
- Modelos: archivos `app/models/<entity>.py` con `<Entity>` (table=True), `<Entity>Read`, `<Entity>Create`
- Routers: `app/api/<resource>.py`, todos registrados en `router.py` bajo prefix `/api/v1`
- Servicios sin estado propio (clases con métodos, inyectables vía Depends)
- Tests: `tests/test_<resource>.py`, fixtures en `conftest.py` (SQLite en memoria, sin lifespan)

### TypeScript (apps/web)
- Imports absolutos vía alias `@/*` (configurado en `tsconfig.app.json` + `vite.config.ts`)
- Componentes shadcn en `src/components/ui/`, primitives bajo `@radix-ui/*`
- Helpers: `cn()` en `src/lib/utils.ts` (clsx + tailwind-merge)
- API client: `src/lib/api.ts` (fetch + proxy `/api/*` en dev → :8000)
- Páginas: `src/pages/<Name>.tsx`, registradas en `App.tsx`

## Multi-tenancy (importante para todo el código)

Cada request lleva un JWT de Clerk → middleware extrae `tenant_id`.
**Todas las queries de la API DEBEN filtrar por `tenant_id`** del usuario autenticado.
Excepción: endpoints `/health/*` y futuros `/admin/*` (super-admin).

(En Fase 0 aún no hay middleware — primer router que necesite tenant scoping
implementa también la dependency `get_current_tenant()`.)

## Cosas a NO hacer

- ❌ No mezclar `Tenant.id` y `clerk_user_id` — son cosas distintas
- ❌ No comitear `.env` (en .gitignore, pero verificar `git status` antes de commit)
- ❌ No `--no-verify` en commits (no hay hooks aún, pero política firme)
- ❌ No reutilizar el workflow n8n viejo — está en pausa, las decisiones de diseño
  se rehacen en este nuevo SaaS
- ❌ No instalar deps Python con `pip install foo` — siempre vía pyproject.toml
  (añadir a `[project.dependencies]` o `[project.optional-dependencies]`)
- ❌ No instalar deps Node con `npm install foo` — siempre `pnpm add foo`
