"""Validación de JWT de Supabase Auth.

Dos modos:
1. **Remoto** (default, no requiere secret): llama a `GET <SUPABASE_URL>/auth/v1/user`
   con el JWT. Supabase responde 200 + user info si es válido, 401 si no.
   Cache in-memory 60s para amortiguar la latencia.
2. **Local HS256** (opcional, más rápido): si está configurado `SUPABASE_JWT_SECRET`,
   verifica firma localmente con `python-jose`. Cero round-trips.

El cache evita que un token válido cueste 1 request remoto por cada llamada al
backend. TTL corto (60s) → si revocas un user, máx 60s de "ventana de validez".
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from jose import JWTError, jwt

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

# Cache: token → (SupabaseUser, expires_at_unix)
_TOKEN_CACHE: dict[str, tuple[SupabaseUser, float]] = {}
_CACHE_TTL_SECONDS = 60.0
# Tope para evitar leak de memoria si llegan muchos tokens distintos.
_CACHE_MAX_ENTRIES = 1000


class AuthError(Exception):
    """JWT inválido, expirado, o config rota."""


@dataclass(frozen=True)
class SupabaseUser:
    id: UUID
    email: str | None
    role: str
    raw_payload: dict[str, Any]


def _cache_get(token: str) -> SupabaseUser | None:
    entry = _TOKEN_CACHE.get(token)
    if entry is None:
        return None
    user, expires_at = entry
    if time.monotonic() > expires_at:
        _TOKEN_CACHE.pop(token, None)
        return None
    return user


def _cache_put(token: str, user: SupabaseUser) -> None:
    if len(_TOKEN_CACHE) >= _CACHE_MAX_ENTRIES:
        # eviction simple: vacía todo. En MVP es ok; cambiar a LRU si crece.
        _TOKEN_CACHE.clear()
    _TOKEN_CACHE[token] = (user, time.monotonic() + _CACHE_TTL_SECONDS)


def _verify_local_hs256(token: str) -> SupabaseUser:
    """Verifica firma localmente con HS256 + secret. Lanza AuthError si falla."""
    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
            options={"verify_aud": True, "verify_exp": True, "verify_iat": True},
        )
    except JWTError as e:
        raise AuthError(f"Token inválido (HS256): {e}") from e
    return _user_from_payload(payload)


def _verify_remote(token: str) -> SupabaseUser:
    """Verifica llamando a Supabase /auth/v1/user. Lanza AuthError si falla."""
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise AuthError(
            "SUPABASE_URL y SUPABASE_ANON_KEY deben estar configurados en .env "
            "para validar tokens remotamente."
        )
    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/user"
    try:
        r = httpx.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": settings.supabase_anon_key,
            },
            timeout=5.0,
        )
    except httpx.HTTPError as e:
        log.error("auth.remote_verify.network_error", error=str(e))
        raise AuthError(f"No se pudo contactar Supabase: {e}") from e

    if r.status_code == 401:
        raise AuthError("Token rechazado por Supabase (401)")
    if r.status_code != 200:
        log.warning("auth.remote_verify.unexpected_status", status=r.status_code, body=r.text[:200])
        raise AuthError(f"Supabase devolvió {r.status_code}")

    data = r.json()
    # /auth/v1/user devuelve el user, no el payload del JWT. Construimos uno equivalente.
    user_id = data.get("id")
    if not user_id:
        raise AuthError("Respuesta de Supabase sin 'id'")
    try:
        user_uuid = UUID(user_id)
    except (ValueError, TypeError) as e:
        raise AuthError(f"id no es UUID: {user_id}") from e
    return SupabaseUser(
        id=user_uuid,
        email=data.get("email"),
        role=data.get("role", "authenticated"),
        raw_payload=data,
    )


def _user_from_payload(payload: dict[str, Any]) -> SupabaseUser:
    sub = payload.get("sub")
    if not sub:
        raise AuthError("Token sin 'sub' (user_id)")
    try:
        user_id = UUID(sub)
    except (ValueError, TypeError) as e:
        raise AuthError(f"'sub' no es UUID: {sub}") from e
    return SupabaseUser(
        id=user_id,
        email=payload.get("email"),
        role=payload.get("role", "authenticated"),
        raw_payload=payload,
    )


def verify_supabase_jwt(token: str) -> SupabaseUser:
    """Verifica un JWT de Supabase. Devuelve el usuario o lanza AuthError.

    Usa cache 60s. Si hay JWT secret configurado, valida local (rápido). Si no,
    valida remoto contra Supabase.
    """
    cached = _cache_get(token)
    if cached is not None:
        return cached

    user = _verify_local_hs256(token) if settings.supabase_jwt_secret else _verify_remote(token)

    _cache_put(token, user)
    return user


def clear_auth_cache() -> None:
    """Limpia el cache de tokens. Útil para tests."""
    _TOKEN_CACHE.clear()
