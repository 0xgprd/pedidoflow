"""Cliente de Microsoft Graph para integración Outlook.

Solo cubre lo necesario para Pedidoflow:
- Intercambio del code OAuth por access/refresh tokens
- Refresh de access tokens
- Listar mensajes de una carpeta
- Descargar attachments

No usamos `msal` para mantener deps al mínimo y porque Graph OAuth con
authorization_code es un POST sencillo.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


def authority(tenant: str | None = None) -> str:
    """Authority URL de Microsoft Identity Platform.

    `common` = cuentas personales + organizacionales
    `consumers` = solo personales
    `<guid>` = un Azure AD tenant específico
    """
    return f"https://login.microsoftonline.com/{tenant or settings.ms_graph_tenant_id}"


def authorize_url(state: str, redirect_uri: str | None = None) -> str:
    """URL a la que redirigir al usuario para iniciar el OAuth flow."""
    from urllib.parse import urlencode

    params = {
        "client_id": settings.ms_graph_client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri or settings.ms_graph_redirect_uri,
        "response_mode": "query",
        "scope": settings.ms_graph_scopes,
        "state": state,
        "prompt": "select_account",
    }
    return f"{authority()}/oauth2/v2.0/authorize?{urlencode(params)}"


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    expires_in: int
    token_type: str = "Bearer"
    scope: str | None = None


class MSGraphError(Exception):
    """Error no recuperable de Microsoft Graph."""


def _token_endpoint() -> str:
    return f"{authority()}/oauth2/v2.0/token"


def exchange_code(code: str, redirect_uri: str | None = None) -> TokenResponse:
    """Cambia un authorization code por access + refresh tokens."""
    if not settings.ms_graph_client_id or not settings.ms_graph_client_secret:
        raise MSGraphError("MS Graph client_id/secret no configurados")

    data = {
        "client_id": settings.ms_graph_client_id,
        "client_secret": settings.ms_graph_client_secret,
        "code": code,
        "redirect_uri": redirect_uri or settings.ms_graph_redirect_uri,
        "grant_type": "authorization_code",
        "scope": settings.ms_graph_scopes,
    }
    resp = httpx.post(_token_endpoint(), data=data, timeout=30.0)
    if resp.status_code != 200:
        log.error("msgraph.token_exchange_failed", status=resp.status_code, body=resp.text[:300])
        raise MSGraphError(f"Token exchange {resp.status_code}: {resp.text[:200]}")
    return TokenResponse.model_validate(resp.json())


def refresh_tokens(refresh_token: str) -> TokenResponse:
    """Renueva access_token con un refresh_token válido."""
    data = {
        "client_id": settings.ms_graph_client_id,
        "client_secret": settings.ms_graph_client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "scope": settings.ms_graph_scopes,
    }
    resp = httpx.post(_token_endpoint(), data=data, timeout=30.0)
    if resp.status_code != 200:
        log.error("msgraph.token_refresh_failed", status=resp.status_code, body=resp.text[:300])
        raise MSGraphError(f"Token refresh {resp.status_code}: {resp.text[:200]}")
    return TokenResponse.model_validate(resp.json())


def expires_at(token: TokenResponse) -> datetime:
    """Calcula timestamp de expiración con margen de 60s de seguridad."""
    return datetime.now(UTC) + timedelta(seconds=max(0, token.expires_in - 60))


# =============================================================================
# Cliente Graph (mensajes + attachments)
# =============================================================================

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}


def get_me(access_token: str) -> dict[str, Any]:
    """Obtiene info del usuario logueado (email, displayName)."""
    resp = httpx.get(f"{GRAPH_BASE}/me", headers=_headers(access_token), timeout=30.0)
    if resp.status_code != 200:
        raise MSGraphError(f"GET /me {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def list_messages_with_attachments(
    access_token: str,
    *,
    folder_id: str | None = None,
    since: datetime | None = None,
    top: int = 50,
) -> list[dict[str, Any]]:
    """Lista mensajes con adjuntos en una carpeta.

    Microsoft Graph rechaza queries que combinan `hasAttachments` + `receivedDateTime`
    + `$orderby` ("InefficientFilter"). Workaround: filtramos solo por `receivedDateTime`
    (campo indexable) + orderby por el mismo campo, y descartamos sin adjuntos en código.
    """
    folder = folder_id or "inbox"
    url = f"{GRAPH_BASE}/me/mailFolders/{folder}/messages"

    params: dict[str, Any] = {
        "$select": "id,subject,from,receivedDateTime,hasAttachments",
        "$orderby": "receivedDateTime desc",
        "$top": top,
    }
    if since is not None:
        # Asegurar que es UTC y formato ISO 8601 con Z
        since_utc = since.astimezone(UTC) if since.tzinfo else since
        params["$filter"] = f"receivedDateTime gt {since_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}"

    resp = httpx.get(url, headers=_headers(access_token), params=params, timeout=30.0)
    if resp.status_code != 200:
        raise MSGraphError(f"List messages {resp.status_code}: {resp.text[:200]}")

    messages = resp.json().get("value", [])
    # Filtrar client-side por adjuntos (más fiable que el filtro server-side)
    return [m for m in messages if m.get("hasAttachments")]


def list_attachments(access_token: str, message_id: str) -> list[dict[str, Any]]:
    url = f"{GRAPH_BASE}/me/messages/{message_id}/attachments"
    resp = httpx.get(url, headers=_headers(access_token), timeout=30.0)
    if resp.status_code != 200:
        raise MSGraphError(f"List attachments {resp.status_code}: {resp.text[:200]}")
    return resp.json().get("value", [])


def download_attachment(access_token: str, message_id: str, attachment_id: str) -> bytes:
    """Descarga el contenido binario de un attachment."""
    import base64

    url = f"{GRAPH_BASE}/me/messages/{message_id}/attachments/{attachment_id}"
    resp = httpx.get(url, headers=_headers(access_token), timeout=60.0)
    if resp.status_code != 200:
        raise MSGraphError(f"Download attachment {resp.status_code}: {resp.text[:200]}")
    payload = resp.json()
    content_b64 = payload.get("contentBytes")
    if not content_b64:
        raise MSGraphError("Attachment sin contentBytes (no es FileAttachment)")
    return base64.b64decode(content_b64)
