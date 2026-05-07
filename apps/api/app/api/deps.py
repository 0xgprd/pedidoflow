"""FastAPI dependencies compartidas — auth Supabase + resolución de tenant."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlmodel import Session, select

from app.core.auth import AuthError, SupabaseUser, verify_supabase_jwt
from app.core.config import settings
from app.core.db import get_session
from app.core.logging import get_logger
from app.models.tenant import Tenant

log = get_logger(__name__)


def _parse_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def get_current_user_optional(
    authorization: Annotated[str | None, Header()] = None,
) -> SupabaseUser | None:
    """Devuelve el usuario Supabase si hay JWT válido, sino None.

    Para endpoints que distinguen "logueado" vs "anónimo" sin forzar.
    """
    token = _parse_bearer(authorization)
    if not token:
        return None
    try:
        return verify_supabase_jwt(token)
    except AuthError:
        return None


def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> SupabaseUser:
    """Requiere un JWT válido. Lanza 401 si no."""
    token = _parse_bearer(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return verify_supabase_jwt(token)
    except AuthError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


def get_current_tenant_id(
    session: Annotated[Session, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
    x_tenant_id: Annotated[UUID | None, Header(alias="X-Tenant-Id")] = None,
) -> UUID:
    """Resuelve el `tenant_id` del request.

    Orden de resolución:
    1. Si hay JWT válido (Authorization: Bearer ...) → busca el Tenant cuyo
       supabase_user_id coincida con el `sub` del token. Si no hay match, 401.
    2. (Solo si `auth_allow_tenant_header_fallback=True`, modo dev/migración)
       Si no hay JWT, acepta `X-Tenant-Id` directo.
    3. Si nada de lo anterior, 401.
    """
    token = _parse_bearer(authorization)
    if token:
        try:
            user = verify_supabase_jwt(token)
        except AuthError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e),
                headers={"WWW-Authenticate": "Bearer"},
            ) from e
        tenant = session.exec(select(Tenant).where(Tenant.supabase_user_id == user.id)).first()
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tenant linked to this user. Call POST /auth/onboard first.",
            )
        return tenant.id

    if settings.auth_allow_tenant_header_fallback and x_tenant_id is not None:
        return x_tenant_id

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing Authorization: Bearer <token> (or X-Tenant-Id en dev)",
        headers={"WWW-Authenticate": "Bearer"},
    )


CurrentTenantId = Annotated[UUID, "tenant_id resolved from auth context"]
