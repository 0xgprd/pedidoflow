"""Tests del CRUD concepts + servicio apply_concepts."""

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.models.concept import Concept
from app.services.concepts import apply_concepts


@pytest.fixture
def tenant_id(client: TestClient) -> UUID:
    r = client.post("/api/v1/tenants", json={"name": "Q", "slug": "q"})
    return UUID(r.json()["id"])


def _auth(t: UUID) -> dict[str, str]:
    return {"X-Tenant-Id": str(t)}


# =============================================================================
# CRUD
# =============================================================================


def test_create_concept_per_tenant(client: TestClient, tenant_id: UUID) -> None:
    payload = {
        "name": "Transporte",
        "code": "FP",
        "aliases": ["freight cost", "frais de port", "shipping"],
        "is_global": False,
    }
    r = client.post("/api/v1/concepts", json=payload, headers=_auth(tenant_id))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Transporte"
    assert body["code"] == "FP"
    assert body["tenant_id"] == str(tenant_id)
    assert "freight cost" in body["aliases"]


def test_create_concept_global(client: TestClient, tenant_id: UUID) -> None:
    r = client.post(
        "/api/v1/concepts",
        json={"name": "IVA 21%", "aliases": ["iva 21", "tva 21"], "is_global": True},
        headers=_auth(tenant_id),
    )
    assert r.status_code == 201
    assert r.json()["tenant_id"] is None


def test_list_includes_global_and_tenant(client: TestClient, tenant_id: UUID) -> None:
    client.post(
        "/api/v1/concepts",
        json={"name": "Local", "aliases": ["x"], "is_global": False},
        headers=_auth(tenant_id),
    )
    client.post(
        "/api/v1/concepts",
        json={"name": "Global", "aliases": ["y"], "is_global": True},
        headers=_auth(tenant_id),
    )
    # otro tenant ve el global pero no el local
    other = UUID(client.post("/api/v1/tenants", json={"name": "O", "slug": "o"}).json()["id"])
    r = client.get("/api/v1/concepts", headers=_auth(other))
    names = [c["name"] for c in r.json()]
    assert "Global" in names
    assert "Local" not in names


def test_aliases_normalized(client: TestClient, tenant_id: UUID) -> None:
    r = client.post(
        "/api/v1/concepts",
        json={"name": "X", "aliases": ["  Hello World  ", "HELLO WORLD", "extra"]},
        headers=_auth(tenant_id),
    )
    assert r.status_code == 201
    aliases = r.json()["aliases"]
    assert "hello world" in aliases
    assert "extra" in aliases
    # deduplicado
    assert aliases.count("hello world") == 1


def test_add_alias_to_existing(client: TestClient, tenant_id: UUID) -> None:
    r = client.post(
        "/api/v1/concepts",
        json={"name": "Transporte", "aliases": ["fp"]},
        headers=_auth(tenant_id),
    )
    cid = r.json()["id"]
    r = client.post(
        f"/api/v1/concepts/{cid}/aliases",
        json={"text": "Frais de port"},
        headers=_auth(tenant_id),
    )
    assert r.status_code == 200
    aliases = r.json()["aliases"]
    assert "frais de port" in aliases
    assert "fp" in aliases


def test_delete_concept(client: TestClient, tenant_id: UUID) -> None:
    r = client.post(
        "/api/v1/concepts",
        json={"name": "X", "aliases": ["a"]},
        headers=_auth(tenant_id),
    )
    cid = r.json()["id"]
    r = client.delete(f"/api/v1/concepts/{cid}", headers=_auth(tenant_id))
    assert r.status_code == 204


def test_cant_delete_other_tenants_concept(client: TestClient, tenant_id: UUID) -> None:
    r = client.post(
        "/api/v1/concepts",
        json={"name": "X", "aliases": ["a"]},
        headers=_auth(tenant_id),
    )
    cid = r.json()["id"]
    other = UUID(client.post("/api/v1/tenants", json={"name": "O", "slug": "o"}).json()["id"])
    r = client.delete(f"/api/v1/concepts/{cid}", headers=_auth(other))
    assert r.status_code == 404


# =============================================================================
# Servicio apply_concepts
# =============================================================================


def _concept(name: str, aliases: list[str], code: str | None = None) -> Concept:
    return Concept(
        id=uuid4(),
        tenant_id=uuid4(),
        name=name,
        code=code,
        aliases=[a.lower() for a in aliases],
    )


def test_apply_substring_match() -> None:
    extracted: dict[str, Any] = {
        "lineas": [{"descripcion": "Frais Divers: FREIGHT COST", "cantidad": 1}]
    }
    concepts = [_concept("Transporte", ["freight cost", "frais de port"], code="FP")]
    result, hits = apply_concepts(extracted, concepts)
    assert result["lineas"][0]["descripcion"] == "Transporte (FP)"
    assert len(hits) == 1


def test_apply_global_and_tenant_concepts() -> None:
    extracted = {"lineas": [{"descripcion": "Shipping fee"}, {"descripcion": "TVA 21"}]}
    concepts = [
        _concept("Transporte", ["shipping"], code="FP"),
        _concept("IVA 21%", ["tva 21", "iva 21%"]),
    ]
    result, _ = apply_concepts(extracted, concepts)
    assert result["lineas"][0]["descripcion"] == "Transporte (FP)"
    assert result["lineas"][1]["descripcion"] == "IVA 21%"


def test_apply_longest_alias_wins() -> None:
    extracted = {"lineas": [{"descripcion": "Frais de port"}]}
    concepts = [
        _concept("Coste menor", ["frais"]),
        _concept("Transporte", ["frais de port"], code="FP"),
    ]
    result, _ = apply_concepts(extracted, concepts)
    assert result["lineas"][0]["descripcion"] == "Transporte (FP)"


def test_apply_preserves_protected_blocks() -> None:
    extracted = {
        "lineas": [{"descripcion": "shipping"}],
        "source_texts": {"lineas.0.descripcion": "shipping"},
        "validation": {"summary": {"blocking": 0}, "lines": []},
        "workflow": {"blocked": False},
    }
    concepts = [_concept("Transporte", ["shipping"])]
    result, _ = apply_concepts(extracted, concepts)
    assert result["lineas"][0]["descripcion"] == "Transporte"
    # Bloques protegidos no se tocan
    assert result["source_texts"]["lineas.0.descripcion"] == "shipping"
    assert result["validation"]["summary"]["blocking"] == 0


def test_apply_no_concepts_passthrough() -> None:
    extracted = {"foo": "bar"}
    result, hits = apply_concepts(extracted, [])
    assert result == extracted
    assert hits == set()


# =============================================================================
# Schema fields + field_path linking
# =============================================================================


def test_list_schema_fields_no_auth(client: TestClient) -> None:
    r = client.get("/api/v1/concepts/schema-fields")
    assert r.status_code == 200
    fields = r.json()
    paths = [f["path"] for f in fields]
    assert "cliente.nombre" in paths
    assert "pedido.numero_pedido_cliente" in paths
    assert all("group" in f for f in fields)


def test_create_concept_with_field_path(client: TestClient, tenant_id: UUID) -> None:
    payload = {
        "name": "Dirección entrega multilingüe",
        "field_path": "cliente.direccion_entrega",
        "aliases": ["adresse de livraison", "shipping address"],
    }
    r = client.post("/api/v1/concepts", json=payload, headers=_auth(tenant_id))
    assert r.status_code == 201, r.text
    assert r.json()["field_path"] == "cliente.direccion_entrega"


def test_invalid_field_path_rejected(client: TestClient, tenant_id: UUID) -> None:
    r = client.post(
        "/api/v1/concepts",
        json={"name": "X", "field_path": "lineas.invented", "aliases": ["a"]},
        headers=_auth(tenant_id),
    )
    assert r.status_code == 400
