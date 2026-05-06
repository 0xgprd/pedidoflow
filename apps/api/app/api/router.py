"""Router principal v1: agrupa todos los routers de la API."""

from fastapi import APIRouter

from app.api import health, tenants

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(tenants.router)
