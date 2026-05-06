# Roadmap MVP — 12 semanas

> Plan estratégico completo: `C:\Users\gperd\.claude\plans\tu-peux-me-dire-parallel-lagoon.md`

## Fase 0 — Setup (semana 1) **← actual**

- [x] Monorepo (`apps/api` + `apps/web`)
- [x] Docker compose (Postgres+pgvector + Redis)
- [x] FastAPI skeleton (health, tenants CRUD, lifespan, structlog)
- [x] React skeleton (Vite + TS + Tailwind + shadcn primitives + router)
- [x] `.env.example` + `.gitignore` + READMEs
- [ ] Levantar entorno local (`docker compose up -d` + `uvicorn` + `pnpm dev`)
- [ ] Deploy Railway staging
- [ ] Integrar Clerk
- [ ] Comprar dominio

## Fase 1 — Document ingestion + extracción (semanas 2-3)

- [ ] Modelo `Document` (id, tenant_id, pdf_url, status, source_email, extracted_json, ...)
- [ ] Endpoint `POST /api/v1/documents` (upload manual)
- [ ] Cliente Cloudflare R2 (boto3) + servicio `storage`
- [ ] Worker Celery `extract_document`
- [ ] Servicio `extraction` con Claude SDK (port del prompt n8n)
- [ ] Endpoints `GET /documents`, `GET /documents/{id}`
- [ ] UI: lista documentos + detalle JSON crudo

## Fase 2 — Catálogo + memoria (semanas 4-5)

- [ ] Modelo `Catalog`, `CatalogItem`, `CatalogMapping`
- [ ] Import CSV/Excel del catálogo (endpoint admin)
- [ ] Cargar catálogo Quimilock (~309 refs)
- [ ] Servicio `lookup` (anti-contaminación + variant disambig + scoring)
- [ ] Modelo `VectorMemory` (pgvector, embeddings 1024 dims con Voyage)
- [ ] Search semántico para fuzzy match
- [ ] Tests con los 5 pedidos reales conocidos

## Fase 3 — UI revisión + field mapping (semanas 6-7)

- [ ] Document viewer (PDF embed react-pdf o pdf.js)
- [ ] Field mapper visual (overlay con campos extraídos resaltados)
- [ ] Acciones: aprobar / rechazar / editar líneas / añadir notas
- [ ] Lista pedidos con filtros (estado, fecha, cliente)
- [ ] Memoria visible: panel de mapeos + reglas + preferencias

## Fase 4 — Conector Outlook (semanas 8-9)

- [ ] Microsoft Graph OAuth (`/integrations/outlook/connect` + callback)
- [ ] Modelo `EmailIntegration` (tenant ↔ folder watched + token refresh)
- [ ] Webhook subscription Graph API
- [ ] Endpoint webhook ingesta → crear Document
- [ ] UI: configurar conexión Outlook + carpeta

## Fase 5 — Sage 200 + workflow excepciones (semanas 10-11)

- [ ] HTTP client Sage 200 (basado en `reference_sage200_api.md`)
- [ ] Auth (Bearer + Ocp-Apim-Subscription-Key + X-Site + X-Nonce)
- [ ] `lookup_customer_id`, `lookup_product_id`
- [ ] `POST /SalesOrders` + polling con `ExternalSalesOrderNumber`
- [ ] Workflow rules engine (precio, ref desconocida, transporte)
- [ ] UI: panel reglas

## Fase 6 — Onboarding Quimilock (semana 12)

- [ ] Migrar Quimilock al SaaS
- [ ] Pruebas con 5 pedidos reales + nuevos
- [ ] Iteración rápida sobre feedback Gabriel
- [ ] Bug fixing
- [ ] Landing + pitch para captar clientes 2-3
