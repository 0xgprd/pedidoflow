"""Tests endpoints tenants."""

from fastapi.testclient import TestClient


def test_create_and_list_tenant(client: TestClient) -> None:
    # Lista vacía
    r = client.get("/api/v1/tenants")
    assert r.status_code == 200
    assert r.json() == []

    # Crear
    payload = {"name": "Quimilock", "slug": "quimilock"}
    r = client.post("/api/v1/tenants", json=payload)
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Quimilock"
    assert body["slug"] == "quimilock"
    assert body["is_active"] is True
    tenant_id = body["id"]

    # GET por id
    r = client.get(f"/api/v1/tenants/{tenant_id}")
    assert r.status_code == 200

    # Conflicto al duplicar slug
    r = client.post("/api/v1/tenants", json=payload)
    assert r.status_code == 409


def test_get_unknown_tenant_404(client: TestClient) -> None:
    r = client.get("/api/v1/tenants/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
