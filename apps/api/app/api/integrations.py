"""Endpoints de integraciones (Outlook, futuro Gmail/...).

Flujo OAuth Outlook:
  1. Frontend llama POST /integrations/outlook/connect
       → backend genera state firmado con tenant_id, devuelve URL de autorización
  2. Usuario autoriza en login.microsoftonline.com
  3. Microsoft redirige a /integrations/outlook/callback?code=...&state=...
       → backend valida state, intercambia code por tokens, crea EmailIntegration
       → redirect 302 al frontend (settings.ms_graph_post_callback_url)
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_current_tenant_id
from app.core.config import settings
from app.core.db import get_session
from app.core.logging import get_logger
from app.models.email_integration import (
    EmailIntegration,
    EmailIntegrationRead,
    IntegrationProvider,
    IntegrationStatus,
)
from app.services import msgraph

log = get_logger(__name__)
router = APIRouter(prefix="/integrations", tags=["integrations"])

_state_signer = URLSafeTimedSerializer(settings.app_secret_key, salt="ms-graph-oauth")
_STATE_MAX_AGE_SECONDS = 600  # 10 min para completar el flow


# =============================================================================
# CRUD listado / borrado
# =============================================================================


@router.get("", response_model=list[EmailIntegrationRead])
def list_integrations(
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> list[EmailIntegration]:
    return list(
        session.exec(
            select(EmailIntegration)
            .where(EmailIntegration.tenant_id == tenant_id)
            .order_by(EmailIntegration.created_at.desc())  # type: ignore[attr-defined]
        ).all()
    )


@router.delete("/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_integration(
    integration_id: UUID,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    obj = session.get(EmailIntegration, integration_id)
    if obj is None or obj.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Integration not found")
    session.delete(obj)
    session.commit()


# =============================================================================
# OAuth Outlook
# =============================================================================


class ConnectResponse(BaseModel):
    authorization_url: str


@router.post("/outlook/connect", response_model=ConnectResponse)
def outlook_connect(
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> ConnectResponse:
    """Genera la URL de autorización Microsoft. El frontend redirige al usuario."""
    if not settings.ms_graph_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Microsoft Graph no configurado. Pide al admin que añada "
                "MS_GRAPH_CLIENT_ID + MS_GRAPH_CLIENT_SECRET al .env."
            ),
        )
    state = _state_signer.dumps({"tenant_id": str(tenant_id), "nonce": str(uuid4())})
    return ConnectResponse(authorization_url=msgraph.authorize_url(state))


@router.get("/outlook/callback")
def outlook_callback(
    session: Annotated[Session, Depends(get_session)],
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
    error_description: Annotated[str | None, Query()] = None,
) -> Response:
    """Microsoft redirige aquí tras autorizar. Intercambia code por tokens."""
    if error:
        log.warning("outlook.callback.error_from_ms", error=error, desc=error_description)
        return RedirectResponse(
            url=f"{settings.ms_graph_post_callback_url}?error={error}",
            status_code=302,
        )
    if not code or not state:
        raise HTTPException(status_code=400, detail="missing code or state")

    try:
        payload = _state_signer.loads(state, max_age=_STATE_MAX_AGE_SECONDS)
    except BadSignature as e:
        log.warning("outlook.callback.bad_state", error=str(e))
        raise HTTPException(status_code=400, detail="invalid state") from e

    tenant_id = UUID(payload["tenant_id"])

    try:
        token = msgraph.exchange_code(code)
        me = msgraph.get_me(token.access_token)
    except msgraph.MSGraphError as e:
        log.error("outlook.callback.exchange_failed", error=str(e))
        return RedirectResponse(
            url=f"{settings.ms_graph_post_callback_url}?error=token_exchange",
            status_code=302,
        )

    email = (me.get("mail") or me.get("userPrincipalName") or "").lower()
    display_name = me.get("displayName")
    if not email:
        raise HTTPException(status_code=502, detail="No email in /me response")

    # Upsert por (tenant, provider, email)
    existing = session.exec(
        select(EmailIntegration).where(
            EmailIntegration.tenant_id == tenant_id,
            EmailIntegration.provider == IntegrationProvider.OUTLOOK,
            EmailIntegration.email == email,
        )
    ).first()

    expires = msgraph.expires_at(token)
    if existing is None:
        integ = EmailIntegration(
            tenant_id=tenant_id,
            provider=IntegrationProvider.OUTLOOK,
            email=email,
            display_name=display_name,
            status=IntegrationStatus.ACTIVE,
            access_token=token.access_token,
            refresh_token=token.refresh_token,
            token_expires_at=expires,
        )
        session.add(integ)
    else:
        existing.access_token = token.access_token
        if token.refresh_token:
            existing.refresh_token = token.refresh_token
        existing.token_expires_at = expires
        existing.display_name = display_name
        existing.status = IntegrationStatus.ACTIVE
        existing.last_error = None
        existing.updated_at = datetime.now(UTC)
        session.add(existing)
    session.commit()

    log.info("outlook.connected", tenant_id=str(tenant_id), email=email)
    return RedirectResponse(
        url=f"{settings.ms_graph_post_callback_url}?connected={email}",
        status_code=302,
    )


# =============================================================================
# Trigger manual de polling (útil para tests + botón "Sincronizar ahora")
# =============================================================================


class PollResponse(BaseModel):
    started: bool
    message: str


@router.post(
    "/outlook/{integration_id}/poll",
    response_model=PollResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_poll(
    integration_id: UUID,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> PollResponse:
    """Dispara el polling de una integración manualmente.

    Devuelve 202 Accepted inmediatamente — no espera al fin del processing.
    El frontend ve los Documents llegar a la bandeja con su polling habitual.
    """
    integ = session.get(EmailIntegration, integration_id)
    if integ is None or integ.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Integration not found")

    from app.workers.tasks import poll_outlook_integration

    if settings.celery_task_always_eager:
        # Dev: ejecutar en thread aparte para no bloquear el HTTP response.
        # La task es síncrona en eager pero el thread la deja correr en background.
        import threading

        threading.Thread(
            target=poll_outlook_integration.apply,
            args=([str(integration_id)],),
            daemon=True,
        ).start()
    else:
        poll_outlook_integration.delay(str(integration_id))

    return PollResponse(
        started=True,
        message="Sincronización iniciada. Los pedidos aparecerán en la bandeja según se procesan.",
    )
