"""Tests endpoints health."""

from fastapi.testclient import TestClient


def test_root(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Pedidoflow API"
    assert "version" in body


def test_health(client: TestClient) -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "timestamp" in body
