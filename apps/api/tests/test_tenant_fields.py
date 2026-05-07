"""Tests del CRUD tenant_fields + integración con concepts/schema-fields."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def tenant_id(client: TestClient) -> UUID:
    r = client.post("/api/v1/tenants", json={"name": "Q", "slug": "q"})
    return UUID(r.json()["id"])


def _auth(t: UUID) -> dict[str, str]:
    return {"X-Tenant-Id": str(t)}


# =============================================================================
# CRUD básico
# =============================================================================


def test_create_tenant_field_auto_key(client: TestClient, tenant_id: UUID) -> None:
    r = client.post(
        "/api/v1/tenant-fields",
        json={"group": "Cliente", "label": "Horario de entrega"},
        headers=_auth(tenant_id),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["group"] == "Cliente"
    assert body["key"] == "horario_de_entrega"
    assert body["label"] == "Horario de entrega"
    assert body["field_path"] == "custom.horario_de_entrega"


def test_create_tenant_field_explicit_key(client: TestClient, tenant_id: UUID) -> None:
    r = client.post(
        "/api/v1/tenant-fields",
        json={"group": "Pedido", "label": "Incoterm", "key": "incoterm"},
        headers=_auth(tenant_id),
    )
    assert r.status_code == 201
    assert r.json()["key"] == "incoterm"


def test_invalid_group_rejected(client: TestClient, tenant_id: UUID) -> None:
    r = client.post(
        "/api/v1/tenant-fields",
        json={"group": "Lineas", "label": "Foo"},
        headers=_auth(tenant_id),
    )
    assert r.status_code == 400


def test_invalid_key_rejected(client: TestClient, tenant_id: UUID) -> None:
    r = client.post(
        "/api/v1/tenant-fields",
        json={"group": "Cliente", "label": "Foo", "key": "1bad-key"},
        headers=_auth(tenant_id),
    )
    assert r.status_code == 400


def test_duplicate_key_per_tenant(client: TestClient, tenant_id: UUID) -> None:
    client.post(
        "/api/v1/tenant-fields",
        json={"group": "Cliente", "label": "Horario", "key": "horario"},
        headers=_auth(tenant_id),
    )
    r = client.post(
        "/api/v1/tenant-fields",
        json={"group": "Pedido", "label": "Otro horario", "key": "horario"},
        headers=_auth(tenant_id),
    )
    assert r.status_code == 409


def test_list_isolated_per_tenant(client: TestClient, tenant_id: UUID) -> None:
    client.post(
        "/api/v1/tenant-fields",
        json={"group": "Cliente", "label": "Horario"},
        headers=_auth(tenant_id),
    )
    other = UUID(client.post("/api/v1/tenants", json={"name": "O", "slug": "o"}).json()["id"])
    r = client.get("/api/v1/tenant-fields", headers=_auth(other))
    assert r.status_code == 200
    assert r.json() == []


def test_update_tenant_field(client: TestClient, tenant_id: UUID) -> None:
    r = client.post(
        "/api/v1/tenant-fields",
        json={"group": "Cliente", "label": "Horario"},
        headers=_auth(tenant_id),
    )
    fid = r.json()["id"]
    r = client.patch(
        f"/api/v1/tenant-fields/{fid}",
        json={"label": "Horario de entrega", "order": 5},
        headers=_auth(tenant_id),
    )
    assert r.status_code == 200
    assert r.json()["label"] == "Horario de entrega"
    assert r.json()["order"] == 5


def test_delete_cascades_concepts(client: TestClient, tenant_id: UUID) -> None:
    r = client.post(
        "/api/v1/tenant-fields",
        json={"group": "Cliente", "label": "Horario", "key": "horario"},
        headers=_auth(tenant_id),
    )
    fid = r.json()["id"]
    field_path = r.json()["field_path"]

    # Crear un Concept enlazado a ese field_path
    r = client.post(
        "/api/v1/concepts",
        json={
            "name": "Horario de entrega",
            "field_path": field_path,
            "aliases": ["horaire", "delivery time"],
        },
        headers=_auth(tenant_id),
    )
    assert r.status_code == 201

    # Borrar el TenantField → debe arrastrar el Concept
    r = client.delete(f"/api/v1/tenant-fields/{fid}", headers=_auth(tenant_id))
    assert r.status_code == 204

    # El concept ya no existe
    concepts = client.get("/api/v1/concepts", headers=_auth(tenant_id)).json()
    assert all(c["field_path"] != field_path for c in concepts)


# =============================================================================
# Integración con /concepts/schema-fields
# =============================================================================


def test_schema_fields_includes_custom_when_tenant_header(
    client: TestClient, tenant_id: UUID
) -> None:
    client.post(
        "/api/v1/tenant-fields",
        json={"group": "Cliente", "label": "Horario de entrega"},
        headers=_auth(tenant_id),
    )
    r = client.get("/api/v1/concepts/schema-fields", headers=_auth(tenant_id))
    assert r.status_code == 200
    fields = r.json()
    paths = [f["path"] for f in fields]
    assert "custom.horario_de_entrega" in paths
    custom_entry = next(f for f in fields if f["path"] == "custom.horario_de_entrega")
    assert custom_entry["is_custom"] is True
    assert custom_entry["group"] == "Cliente"


def test_schema_fields_no_tenant_returns_only_fixed(client: TestClient, tenant_id: UUID) -> None:
    client.post(
        "/api/v1/tenant-fields",
        json={"group": "Cliente", "label": "Horario"},
        headers=_auth(tenant_id),
    )
    # Sin header X-Tenant-Id
    r = client.get("/api/v1/concepts/schema-fields")
    assert r.status_code == 200
    paths = [f["path"] for f in r.json()]
    assert "custom.horario" not in paths
    # Pero los fijos sí
    assert "cliente.nombre" in paths


# =============================================================================
# Concept con field_path = custom.<key>
# =============================================================================


def test_concept_with_custom_field_path(client: TestClient, tenant_id: UUID) -> None:
    client.post(
        "/api/v1/tenant-fields",
        json={"group": "Cliente", "label": "Horario", "key": "horario"},
        headers=_auth(tenant_id),
    )
    r = client.post(
        "/api/v1/concepts",
        json={
            "name": "Horario",
            "field_path": "custom.horario",
            "aliases": ["horaire", "delivery hours"],
        },
        headers=_auth(tenant_id),
    )
    assert r.status_code == 201, r.text
    assert r.json()["field_path"] == "custom.horario"


def test_concept_with_unknown_custom_path_rejected(client: TestClient, tenant_id: UUID) -> None:
    r = client.post(
        "/api/v1/concepts",
        json={
            "name": "X",
            "field_path": "custom.no_existe",
            "aliases": ["x"],
        },
        headers=_auth(tenant_id),
    )
    assert r.status_code == 400


# =============================================================================
# Nuevos campos fijos
# =============================================================================


def test_new_fixed_fields_present(client: TestClient) -> None:
    r = client.get("/api/v1/concepts/schema-fields")
    assert r.status_code == 200
    paths = [f["path"] for f in r.json()]
    assert "cliente.numero_iva" in paths
    assert "cliente.direccion_facturacion" in paths
    assert "totales.transporte" in paths
