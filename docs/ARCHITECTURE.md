# Arquitectura

## Vista general

```
                    ┌─────────────────────────────────────────┐
                    │  Web (React + Tailwind + shadcn)        │
                    │  - Inbox · Document viewer · Field map  │
                    └────────────────┬────────────────────────┘
                                     │ HTTPS / JSON
                    ┌────────────────▼────────────────────────┐
                    │  API (FastAPI)                          │
                    │  - REST · Auth Clerk · OpenAPI          │
                    │  - Background jobs (Celery)             │
                    └────────────────┬────────────────────────┘
        ┌────────────────────────────┼────────────────────────────┐
        ▼                            ▼                            ▼
  ┌────────────┐              ┌──────────────┐           ┌──────────────┐
  │ Postgres   │              │  Claude API  │           │ Sage 200 API │
  │ + pgvector │              │  + Voyage AI │           │ (carga real) │
  │ + pg_trgm  │              │  embeddings  │           └──────────────┘
  └────────────┘              └──────────────┘           ┌──────────────┐
  ┌────────────┐                                         │ MS Graph API │
  │  S3 / R2   │                                         │  (Outlook)   │
  │  (PDFs)    │                                         └──────────────┘
  └────────────┘
```

## Decisiones (ADRs informales)

### ADR-001: Postgres con pgvector como única DB
- **Contexto**: necesitamos relacional (tenants, mappings, rules) + vectorial (memoria fuzzy).
- **Decisión**: Postgres 16 + pgvector. Sin Pinecone/Weaviate dedicado.
- **Razón**: una sola DB = menos ops, transacciones cross-data, suficiente para <10M vectores.

### ADR-002: FastAPI + SQLModel
- **Contexto**: backend Python solo dev + Claude Code.
- **Decisión**: FastAPI + SQLModel (mismo equipo Pydantic).
- **Razón**: async-first, tipado, OpenAPI gratis, Pydantic v2 ya integrado.

### ADR-003: Celery + Redis para jobs IA
- **Contexto**: extracción PDF puede tardar 10-30s.
- **Decisión**: Celery (broker Redis) en vez de FastAPI BackgroundTasks.
- **Razón**: retries, scheduling, visibilidad, supervivencia entre deploys.

### ADR-004: Claude Sonnet 4.6 para extracción
- **Contexto**: comparado con GPT-4o.
- **Decisión**: Claude por mejor reasoning con tablas y prompt caching nativo.
- **Razón**: pedidos tienen mucha tabla; cachear prompt-system reduce coste 90%.

### ADR-005: Multi-tenancy por columna `tenant_id`
- **Contexto**: 1 BD compartida vs 1 BD por tenant.
- **Decisión**: shared DB, scoping por `tenant_id` en cada query.
- **Razón**: simpler, cheaper, suficiente para <100 tenants. Migración futura es posible.

### ADR-006: Cloudflare R2 para PDFs
- **Contexto**: storage S3-compatible.
- **Decisión**: R2 sobre AWS S3.
- **Razón**: sin egress fees (importante porque PDFs se descargan a UI).

## Modelo de datos (esbozo, fase 0)

```
tenants                       # 1 cliente del SaaS
  id (uuid, pk)
  name, slug, is_active

# Pendiente fases siguientes:
users           tenant_id, clerk_user_id, role
documents       tenant_id, source, pdf_url, status, extracted_json, ...
catalogs        tenant_id, name, ...
catalog_items   catalog_id, ref, name, price, ...
mappings        tenant_id, customer_ref, internal_ref
rules           tenant_id, type, payload (jsonb)
vector_memory   tenant_id, document_id, embedding (vector(1024)), payload
sage_orders     tenant_id, document_id, sage_id, status
audit_logs      tenant_id, actor, action, payload, created_at
```

## Multi-tenancy

- Cada request lleva un JWT Clerk → middleware extrae `tenant_id`
- Todas las queries de la API llevan filtro `WHERE tenant_id = :current_tenant`
- (Futuro) considerar Postgres RLS si crecemos a >50 tenants

## Seguridad

- Auth: JWT Clerk validado por API
- Secretos en env vars (Railway secrets, no en repo)
- API keys de Sage/Outlook por tenant: encriptadas en DB (Fernet, key en env)
- CORS restringido a dominios conocidos
- Rate limiting (a añadir post-MVP)

## Observabilidad

- Logs estructurados JSON via structlog
- Errores → Sentry
- Traces app → Logfire (FastAPI native)
- Métricas Postgres → Railway dashboard
