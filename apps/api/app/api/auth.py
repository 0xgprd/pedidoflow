"""Endpoints de autenticación / onboarding.

Flujo MVP (1 user = 1 tenant):
- El user hace signup en Supabase (frontend con `@supabase/supabase-js`).
- Supabase devuelve un JWT. El frontend lo manda en `Authorization: Bearer ...`.
- En el primer request a `POST /auth/onboard`, creamos el Tenant del user.
- A partir de ahí `get_current_tenant_id()` resuelve el tenant via el JWT.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.api.deps import get_current_user
from app.core.auth import SupabaseUser
from app.core.db import get_session
from app.core.logging import get_logger
from app.models.tenant import Tenant, TenantRead

log = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class OnboardRequest(BaseModel):
    """Datos opcionales del primer signup. Si faltan, se derivan del email."""

    name: str | None = Field(default=None, max_length=200)
    slug: str | None = Field(default=None, max_length=100)
    # MVP: opcional. Si el user mete un slug que ya existe (ej. "quimilock"
    # del tenant huérfano legacy), reclamamos ese tenant en vez de crear uno nuevo.
    claim_slug: str | None = Field(default=None, max_length=100)


class MeResponse(BaseModel):
    user_id: UUID
    email: str | None
    tenant: TenantRead | None  # null si aún no ha hecho onboarding


def _slug_from_email(email: str | None, fallback_id: UUID) -> str:
    if not email or "@" not in email:
        return f"u-{fallback_id.hex[:8]}"
    local = email.split("@", 1)[0]
    cleaned = "".join(c if c.isalnum() else "-" for c in local.lower()).strip("-")
    return cleaned or f"u-{fallback_id.hex[:8]}"


@router.get("/me", response_model=MeResponse)
def get_me(
    user: Annotated[SupabaseUser, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
) -> MeResponse:
    """Devuelve el user logueado + su tenant (si tiene)."""
    tenant = session.exec(select(Tenant).where(Tenant.supabase_user_id == user.id)).first()
    return MeResponse(
        user_id=user.id,
        email=user.email,
        tenant=TenantRead.model_validate(tenant.model_dump()) if tenant else None,
    )


@router.post("/onboard", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
def onboard(
    payload: OnboardRequest,
    user: Annotated[SupabaseUser, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
) -> Tenant:
    """Crea (o reclama) un Tenant para el user logueado. Idempotente.

    Reglas:
    - Si el user ya tiene tenant, lo devuelve (no error).
    - Si pasa `claim_slug` y existe un Tenant huérfano (supabase_user_id IS NULL)
      con ese slug, lo reclama.
    - Si no, crea un Tenant nuevo con name + slug del payload, o derivados del email.
    """
    existing = session.exec(select(Tenant).where(Tenant.supabase_user_id == user.id)).first()
    if existing is not None:
        return existing

    # Reclamar tenant huérfano por slug
    if payload.claim_slug:
        orphan = session.exec(
            select(Tenant).where(
                Tenant.slug == payload.claim_slug,
                Tenant.supabase_user_id.is_(None),  # type: ignore[union-attr]
            )
        ).first()
        if orphan is not None:
            orphan.supabase_user_id = user.id
            orphan.updated_at = datetime.now(UTC)
            session.add(orphan)
            session.commit()
            session.refresh(orphan)
            log.info(
                "auth.tenant_claimed",
                tenant_id=str(orphan.id),
                user_id=str(user.id),
                slug=orphan.slug,
            )
            return orphan
        # Si pidió claim pero no encuentra huérfano, error explícito
        raise HTTPException(
            status_code=404,
            detail=f"No orphan tenant with slug '{payload.claim_slug}' available to claim",
        )

    # Crear tenant nuevo
    name = (payload.name or "").strip() or (user.email or "Mi empresa").split("@", 1)[0]
    slug = (payload.slug or "").strip() or _slug_from_email(user.email, user.id)

    # Slug único — si choca, sufijar con id corto del user
    dup = session.exec(select(Tenant).where(Tenant.slug == slug)).first()
    if dup is not None:
        slug = f"{slug}-{user.id.hex[:6]}"

    tenant = Tenant(
        name=name,
        slug=slug,
        supabase_user_id=user.id,
    )
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    log.info(
        "auth.tenant_created",
        tenant_id=str(tenant.id),
        user_id=str(user.id),
        slug=tenant.slug,
    )
    return tenant
