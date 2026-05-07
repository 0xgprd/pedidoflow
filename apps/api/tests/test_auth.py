"""Tests de auth: /auth/me, /auth/onboard, get_current_tenant_id via JWT."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core import auth as auth_module
from app.core.auth import SupabaseUser


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    auth_module.clear_auth_cache()


def _make_user(user_id: UUID | None = None, email: str = "test@example.com") -> SupabaseUser:
    return SupabaseUser(
        id=user_id or uuid4(),
        email=email,
        role="authenticated",
        raw_payload={"sub": str(user_id or uuid4()), "email": email},
    )


@pytest.fixture
def fake_jwt(monkeypatch: pytest.MonkeyPatch) -> tuple[str, SupabaseUser]:
    """Devuelve (token_string, user). monkeypatcheamos verify_supabase_jwt."""
    user = _make_user()
    token = "fake.jwt.token"

    def fake_verify(t: str) -> SupabaseUser:
        if t != token:
            from app.core.auth import AuthError

            raise AuthError("token desconocido")
        return user

    monkeypatch.setattr("app.core.auth.verify_supabase_jwt", fake_verify)
    monkeypatch.setattr("app.api.deps.verify_supabase_jwt", fake_verify)
    return token, user


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# /auth/me
# =============================================================================


def test_me_requires_auth(client: TestClient) -> None:
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401


def test_me_invalid_token(client: TestClient, fake_jwt: tuple[str, SupabaseUser]) -> None:
    r = client.get("/api/v1/auth/me", headers=_bearer("otro.token"))
    assert r.status_code == 401


def test_me_no_tenant_yet(client: TestClient, fake_jwt: tuple[str, SupabaseUser]) -> None:
    token, user = fake_jwt
    r = client.get("/api/v1/auth/me", headers=_bearer(token))
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == str(user.id)
    assert body["email"] == user.email
    assert body["tenant"] is None


# =============================================================================
# /auth/onboard
# =============================================================================


def test_onboard_creates_new_tenant(client: TestClient, fake_jwt: tuple[str, SupabaseUser]) -> None:
    token, user = fake_jwt
    r = client.post(
        "/api/v1/auth/onboard",
        json={"name": "ACME Industries", "slug": "acme"},
        headers=_bearer(token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "ACME Industries"
    assert body["slug"] == "acme"

    # /auth/me ahora devuelve el tenant
    r = client.get("/api/v1/auth/me", headers=_bearer(token))
    assert r.json()["tenant"]["slug"] == "acme"


def test_onboard_idempotent(client: TestClient, fake_jwt: tuple[str, SupabaseUser]) -> None:
    token, _ = fake_jwt
    r1 = client.post(
        "/api/v1/auth/onboard", json={"name": "ACME", "slug": "acme"}, headers=_bearer(token)
    )
    assert r1.status_code == 201
    r2 = client.post(
        "/api/v1/auth/onboard", json={"name": "OTRO", "slug": "otro"}, headers=_bearer(token)
    )
    assert r2.status_code == 201
    # Devolvió el ya existente, no creó uno nuevo
    assert r1.json()["id"] == r2.json()["id"]
    assert r2.json()["slug"] == "acme"


def test_onboard_derives_slug_from_email(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user(email="gabriel.perdomo@quimilock.com")
    token = "fake.jwt"

    def fake_verify(t: str) -> SupabaseUser:
        return user

    monkeypatch.setattr("app.core.auth.verify_supabase_jwt", fake_verify)
    monkeypatch.setattr("app.api.deps.verify_supabase_jwt", fake_verify)

    r = client.post("/api/v1/auth/onboard", json={}, headers=_bearer(token))
    assert r.status_code == 201
    assert r.json()["slug"] == "gabriel-perdomo"


def test_claim_orphan_tenant(client: TestClient, fake_jwt: tuple[str, SupabaseUser]) -> None:
    token, user = fake_jwt
    # Crear primero un tenant huérfano (sin user) via endpoint legacy
    r = client.post("/api/v1/tenants", json={"name": "Quimilock Legacy", "slug": "quimi-legacy"})
    assert r.status_code == 201
    legacy_id = r.json()["id"]

    # Reclamarlo via /auth/onboard?claim_slug=
    r = client.post(
        "/api/v1/auth/onboard",
        json={"claim_slug": "quimi-legacy"},
        headers=_bearer(token),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == legacy_id  # mismo tenant, ahora vinculado al user
    assert body["slug"] == "quimi-legacy"


def test_claim_nonexistent_slug_404(client: TestClient, fake_jwt: tuple[str, SupabaseUser]) -> None:
    token, _ = fake_jwt
    r = client.post(
        "/api/v1/auth/onboard",
        json={"claim_slug": "no-existe"},
        headers=_bearer(token),
    )
    assert r.status_code == 404


# =============================================================================
# get_current_tenant_id via JWT
# =============================================================================


def test_jwt_resolves_tenant_id_for_authenticated_endpoints(
    client: TestClient, fake_jwt: tuple[str, SupabaseUser]
) -> None:
    """Tras hacer onboard, los endpoints normales (con tenant scope) funcionan
    con el Authorization header sin necesitar X-Tenant-Id."""
    token, _ = fake_jwt
    r = client.post("/api/v1/auth/onboard", json={"name": "X", "slug": "x"}, headers=_bearer(token))
    assert r.status_code == 201

    # Endpoint normal (concepts) sin X-Tenant-Id, solo Authorization
    r = client.get("/api/v1/concepts", headers=_bearer(token))
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_jwt_user_without_tenant_gets_403(
    client: TestClient, fake_jwt: tuple[str, SupabaseUser]
) -> None:
    """User logueado sin tenant → 403 (debe llamar onboard)."""
    token, _ = fake_jwt
    r = client.get("/api/v1/concepts", headers=_bearer(token))
    assert r.status_code == 403
    assert "onboard" in r.json()["detail"].lower()


def test_x_tenant_id_fallback_still_works(client: TestClient) -> None:
    """En modo dev/migración, X-Tenant-Id sigue funcionando (sin JWT)."""
    r = client.post("/api/v1/tenants", json={"name": "Z", "slug": "z"})
    tid = r.json()["id"]
    r = client.get("/api/v1/concepts", headers={"X-Tenant-Id": tid})
    assert r.status_code == 200
