"""Router principal v1: agrupa todos los routers de la API."""

from fastapi import APIRouter

from app.api import (
    catalog_items,
    dashboard,
    documents,
    field_mappings,
    health,
    integrations,
    tenants,
    workflow_rules,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(tenants.router)
api_router.include_router(documents.router)
api_router.include_router(field_mappings.router)
api_router.include_router(integrations.router)
api_router.include_router(catalog_items.router)
api_router.include_router(workflow_rules.router)
api_router.include_router(dashboard.router)
