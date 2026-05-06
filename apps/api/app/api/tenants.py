"""Endpoints CRUD básico de Tenants (clientes del SaaS).

NOTA: en MVP esto es admin-only. Cuando haya self-service signup,
los tenants se crearán via webhook de Clerk.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.core.db import get_session
from app.models.tenant import Tenant, TenantCreate, TenantRead

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("", response_model=list[TenantRead])
def list_tenants(session: Annotated[Session, Depends(get_session)]) -> list[Tenant]:
    return list(session.exec(select(Tenant)).all())


@router.post("", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
def create_tenant(
    payload: TenantCreate,
    session: Annotated[Session, Depends(get_session)],
) -> Tenant:
    existing = session.exec(select(Tenant).where(Tenant.slug == payload.slug)).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tenant with slug '{payload.slug}' already exists",
        )
    tenant = Tenant(name=payload.name, slug=payload.slug)
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    return tenant


@router.get("/{tenant_id}", response_model=TenantRead)
def get_tenant(
    tenant_id: UUID,
    session: Annotated[Session, Depends(get_session)],
) -> Tenant:
    tenant = session.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant
