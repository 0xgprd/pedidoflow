"""Tests del CRUD field-mappings + servicio apply_mappings."""

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.models.field_mapping import FieldMapping
from app.services.field_mapping import apply_mappings


@pytest.fixture
def tenant_id(client: TestClient) -> UUID:
    r = client.post("/api/v1/tenants", json={"name": "Quimilock", "slug": "quimilock"})
    assert r.status_code == 201
    return UUID(r.json()["id"])


def _auth(t: UUID) -> dict[str, str]:
    return {"X-Tenant-Id": str(t)}


# =============================================================================
# CRUD endpoints
# =============================================================================


def test_list_empty(client: TestClient, tenant_id: UUID) -> None:
    r = client.get("/api/v1/field-mappings", headers=_auth(tenant_id))
    assert r.status_code == 200
    assert r.json() == []


def test_create_mapping(client: TestClient, tenant_id: UUID) -> None:
    payload = {
        "source_text": "FREIGHT COST",
        "canonical_value": "Transporte",
        "canonical_code": "FP",
    }
    r = client.post("/api/v1/field-mappings", json=payload, headers=_auth(tenant_id))
    assert r.status_code == 201
    body = r.json()
    assert body["source_text"] == "FREIGHT COST"
    assert body["canonical_value"] == "Transporte"
    assert body["canonical_code"] == "FP"
    assert body["hits"] == 0


def test_create_is_upsert(client: TestClient, tenant_id: UUID) -> None:
    """POST con mismo source_text normalizado actualiza, no duplica."""
    client.post(
        "/api/v1/field-mappings",
        json={"source_text": "Freight Cost", "canonical_value": "Transporte"},
        headers=_auth(tenant_id),
    )
    r = client.post(
        "/api/v1/field-mappings",
        json={"source_text": "FREIGHT COST", "canonical_value": "Transporte FR", "canonical_code": "FP"},
        headers=_auth(tenant_id),
    )
    assert r.status_code == 201
    assert r.json()["canonical_value"] == "Transporte FR"
    # Solo hay 1 mapping
    r = client.get("/api/v1/field-mappings", headers=_auth(tenant_id))
    assert len(r.json()) == 1


def test_validation_empty_source_or_value(client: TestClient, tenant_id: UUID) -> None:
    r = client.post(
        "/api/v1/field-mappings",
        json={"source_text": "  ", "canonical_value": "X"},
        headers=_auth(tenant_id),
    )
    assert r.status_code == 400
    r = client.post(
        "/api/v1/field-mappings",
        json={"source_text": "X", "canonical_value": "  "},
        headers=_auth(tenant_id),
    )
    assert r.status_code == 400


def test_patch_mapping(client: TestClient, tenant_id: UUID) -> None:
    r = client.post(
        "/api/v1/field-mappings",
        json={"source_text": "Ship", "canonical_value": "Transporte"},
        headers=_auth(tenant_id),
    )
    mid = r.json()["id"]
    r = client.patch(
        f"/api/v1/field-mappings/{mid}",
        json={"canonical_code": "FP", "field_path_pattern": "lineas.*.descripcion"},
        headers=_auth(tenant_id),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["canonical_code"] == "FP"
    assert body["field_path_pattern"] == "lineas.*.descripcion"


def test_delete_mapping(client: TestClient, tenant_id: UUID) -> None:
    r = client.post(
        "/api/v1/field-mappings",
        json={"source_text": "x", "canonical_value": "y"},
        headers=_auth(tenant_id),
    )
    mid = r.json()["id"]
    r = client.delete(f"/api/v1/field-mappings/{mid}", headers=_auth(tenant_id))
    assert r.status_code == 204
    r = client.get("/api/v1/field-mappings", headers=_auth(tenant_id))
    assert r.json() == []


def test_isolation_by_tenant(client: TestClient, tenant_id: UUID) -> None:
    r = client.post(
        "/api/v1/field-mappings",
        json={"source_text": "X", "canonical_value": "Y"},
        headers=_auth(tenant_id),
    )
    mid = r.json()["id"]

    other = UUID(client.post("/api/v1/tenants", json={"name": "Other", "slug": "other"}).json()["id"])
    r = client.get("/api/v1/field-mappings", headers=_auth(other))
    assert r.json() == []
    r = client.delete(f"/api/v1/field-mappings/{mid}", headers=_auth(other))
    assert r.status_code == 404


# =============================================================================
# Servicio apply_mappings
# =============================================================================


def _mapping(
    source: str,
    canonical: str,
    code: str | None = None,
    pattern: str | None = None,
) -> FieldMapping:
    return FieldMapping(
        id=uuid4(),
        tenant_id=uuid4(),
        source_text=source,
        source_text_normalized=source.strip().lower(),
        canonical_value=canonical,
        canonical_code=code,
        field_path_pattern=pattern,
    )


def test_apply_substring_match() -> None:
    extracted: dict[str, Any] = {
        "lineas": [
            {"descripcion": "Frais Divers: FREIGHT COST", "cantidad": 1},
        ]
    }
    mappings = [_mapping("FREIGHT COST", "Transporte", code="FP")]
    result, hits = apply_mappings(extracted, mappings)
    assert result["lineas"][0]["descripcion"] == "Transporte (FP)"
    assert len(hits) == 1


def test_apply_case_insensitive() -> None:
    extracted = {"lineas": [{"descripcion": "shipping fee"}]}
    mappings = [_mapping("Ship", "Transporte")]
    result, hits = apply_mappings(extracted, mappings)
    assert result["lineas"][0]["descripcion"] == "Transporte"
    assert len(hits) == 1


def test_apply_longest_match_wins() -> None:
    """Mapping más específico tiene prioridad."""
    extracted = {"lineas": [{"descripcion": "FREIGHT COST"}]}
    mappings = [
        _mapping("Freight", "Transporte"),
        _mapping("Freight Cost", "Transporte (FP)"),  # más específico
    ]
    result, _ = apply_mappings(extracted, mappings)
    assert result["lineas"][0]["descripcion"] == "Transporte (FP)"


def test_apply_field_path_pattern() -> None:
    """Pattern restringe dónde aplica el mapping."""
    extracted = {
        "cliente": {"nombre": "FREIGHT GLOBAL SA"},  # no debe cambiarse
        "lineas": [{"descripcion": "FREIGHT COST"}],
    }
    mappings = [
        _mapping("FREIGHT", "Transporte", pattern="lineas.*.descripcion"),
    ]
    result, hits = apply_mappings(extracted, mappings)
    assert result["cliente"]["nombre"] == "FREIGHT GLOBAL SA"
    assert result["lineas"][0]["descripcion"] == "Transporte"
    assert len(hits) == 1


def test_apply_preserves_source_texts() -> None:
    """source_texts se mantiene literal — es para overlay sobre el PDF."""
    extracted = {
        "lineas": [{"descripcion": "FREIGHT COST"}],
        "source_texts": {"lineas.0.descripcion": "FREIGHT COST"},
    }
    mappings = [_mapping("FREIGHT COST", "Transporte")]
    result, _ = apply_mappings(extracted, mappings)
    assert result["lineas"][0]["descripcion"] == "Transporte"
    assert result["source_texts"]["lineas.0.descripcion"] == "FREIGHT COST"


def test_apply_no_mappings_passthrough() -> None:
    extracted = {"foo": "bar", "lineas": []}
    result, hits = apply_mappings(extracted, [])
    assert result == extracted
    assert hits == set()
