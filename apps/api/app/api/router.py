"""Router principal v1: agrupa todos los routers de la API."""

from fastapi import APIRouter

from app.api import (
    auth,
    catalog_items,
    concepts,
    dashboard,
    documents,
    health,
    integrations,
    tenant_fields,
    tenants,
    vies,
    workflow_rules,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(tenants.router)
api_router.include_router(documents.router)
api_router.include_router(concepts.router)
api_router.include_router(tenant_fields.router)
api_router.include_router(integrations.router)
api_router.include_router(catalog_items.router)
api_router.include_router(workflow_rules.router)
api_router.include_router(dashboard.router)
api_router.include_router(vies.router)
