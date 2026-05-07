"""Tests del CRUD catalog-items, upload CSV y servicio validate_against_catalog."""

import io
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.models.catalog_item import CatalogItem
from app.services.validation import validate_against_catalog


@pytest.fixture
def tenant_id(client: TestClient) -> UUID:
    r = client.post("/api/v1/tenants", json={"name": "Quimilock", "slug": "quimilock"})
    assert r.status_code == 201
    return UUID(r.json()["id"])


def _auth(t: UUID) -> dict[str, str]:
    return {"X-Tenant-Id": str(t)}


# =============================================================================
# CRUD
# =============================================================================


def test_create_and_list(client: TestClient, tenant_id: UUID) -> None:
    payload = {
        "reference": "TF-75",
        "description": "Tubo flexible 75mm",
        "unit": "ML",
        "min_price": "12.50",
        "currency": "EUR",
    }
    r = client.post("/api/v1/catalog-items", json=payload, headers=_auth(tenant_id))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["reference"] == "TF-75"
    assert Decimal(body["min_price"]) == Decimal("12.50")

    r = client.get("/api/v1/catalog-items", headers=_auth(tenant_id))
    assert len(r.json()) == 1


def test_upsert_by_reference(client: TestClient, tenant_id: UUID) -> None:
    """POST con misma reference normalizada actualiza, no duplica."""
    client.post(
        "/api/v1/catalog-items",
        json={"reference": "tf-75", "min_price": "10"},
        headers=_auth(tenant_id),
    )
    r = client.post(
        "/api/v1/catalog-items",
        json={"reference": "TF-75", "min_price": "15"},
        headers=_auth(tenant_id),
    )
    assert r.status_code == 201
    assert Decimal(r.json()["min_price"]) == Decimal("15")
    r = client.get("/api/v1/catalog-items", headers=_auth(tenant_id))
    assert len(r.json()) == 1


def test_search_by_reference(client: TestClient, tenant_id: UUID) -> None:
    for ref in ("TF-75", "TF-100", "GF-1"):
        client.post(
            "/api/v1/catalog-items",
            json={"reference": ref, "min_price": "10"},
            headers=_auth(tenant_id),
        )
    r = client.get("/api/v1/catalog-items?search=TF", headers=_auth(tenant_id))
    refs = sorted(item["reference"] for item in r.json())
    assert refs == ["TF-100", "TF-75"]


def test_isolation_by_tenant(client: TestClient, tenant_id: UUID) -> None:
    client.post(
        "/api/v1/catalog-items",
        json={"reference": "TF-75", "min_price": "10"},
        headers=_auth(tenant_id),
    )
    other = UUID(client.post("/api/v1/tenants", json={"name": "Other", "slug": "other"}).json()["id"])
    r = client.get("/api/v1/catalog-items", headers=_auth(other))
    assert r.json() == []


# =============================================================================
# Upload CSV
# =============================================================================


def test_upload_csv_basic(client: TestClient, tenant_id: UUID) -> None:
    csv_content = (
        "reference,description,unit,min_price,currency\n"
        "TF-75,Tubo flexible 75,ML,12.50,EUR\n"
        "TF-100,Tubo flexible 100,ML,18.00,EUR\n"
        "GF-1,Goma flexible,UD,5.50,EUR\n"
    )
    files = {"file": ("catalogo.csv", io.BytesIO(csv_content.encode()), "text/csv")}
    r = client.post("/api/v1/catalog-items/upload", files=files, headers=_auth(tenant_id))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 3
    assert body["updated"] == 0
    assert body["skipped"] == 0


def test_upload_csv_semicolon_european(client: TestClient, tenant_id: UUID) -> None:
    """Tolera CSVs europeos (separador ;, decimal ,)."""
    csv_content = (
        "reference;description;min_price;currency\n"
        "TF-75;Tubo flexible 75;12,50;EUR\n"
    )
    files = {"file": ("c.csv", io.BytesIO(csv_content.encode()), "text/csv")}
    r = client.post("/api/v1/catalog-items/upload", files=files, headers=_auth(tenant_id))
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1
    r = client.get("/api/v1/catalog-items", headers=_auth(tenant_id))
    assert Decimal(r.json()[0]["min_price"]) == Decimal("12.50")


def test_upload_csv_updates_existing(client: TestClient, tenant_id: UUID) -> None:
    client.post(
        "/api/v1/catalog-items",
        json={"reference": "TF-75", "min_price": "10"},
        headers=_auth(tenant_id),
    )
    csv_content = "reference,min_price\nTF-75,12.50\nGF-1,5\n"
    files = {"file": ("c.csv", io.BytesIO(csv_content.encode()), "text/csv")}
    r = client.post("/api/v1/catalog-items/upload", files=files, headers=_auth(tenant_id))
    body = r.json()
    assert body["created"] == 1  # GF-1
    assert body["updated"] == 1  # TF-75


def test_upload_csv_missing_reference_column(client: TestClient, tenant_id: UUID) -> None:
    csv_content = "code_x,description\nTF-75,foo\n"
    files = {"file": ("c.csv", io.BytesIO(csv_content.encode()), "text/csv")}
    r = client.post("/api/v1/catalog-items/upload", files=files, headers=_auth(tenant_id))
    assert r.status_code == 400


def test_upload_csv_quimilock_format(client: TestClient, tenant_id: UUID) -> None:
    """Acepta el formato real de Quimilock: 'Ref, Description, Precio unitario' con €X,YZ."""
    csv_content = (
        "Ref,Description,Precio unitario,Peso,Longitud,Mapeo Refs Clientes\n"
        'T1-400 BLANC,Tubo de acero,"€8,20","2,700",4,\n'
        'TF-75,,"€16,90","0,380",1,\n'
        'GF-1,,"€0,85","0,012",1,\n'
    )
    # Encoding utf-8-sig para simular BOM como Excel exporta
    files = {"file": ("c.csv", io.BytesIO(b"\xef\xbb\xbf" + csv_content.encode("utf-8")), "text/csv")}
    r = client.post("/api/v1/catalog-items/upload", files=files, headers=_auth(tenant_id))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 3
    assert body["skipped"] == 0

    r = client.get("/api/v1/catalog-items?search=TF-75", headers=_auth(tenant_id))
    item = next(i for i in r.json() if i["reference"] == "TF-75")
    assert Decimal(item["min_price"]) == Decimal("16.90")


def test_upload_csv_alias_french(client: TestClient, tenant_id: UUID) -> None:
    """Acepta alias en francés: ref/designation/prix."""
    csv_content = "ref;designation;prix;devise\nTF-75;Tube flexible;15,50;EUR\n"
    files = {"file": ("c.csv", io.BytesIO(csv_content.encode()), "text/csv")}
    r = client.post("/api/v1/catalog-items/upload", files=files, headers=_auth(tenant_id))
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1
    r = client.get("/api/v1/catalog-items", headers=_auth(tenant_id))
    item = r.json()[0]
    assert item["description"] == "Tube flexible"
    assert Decimal(item["min_price"]) == Decimal("15.50")


def test_upload_csv_thousands_separator(client: TestClient, tenant_id: UUID) -> None:
    """Maneja '1.234,56' (formato europeo con miles)."""
    csv_content = "reference,min_price\nBIG-1,\"1.234,56\"\n"
    files = {"file": ("c.csv", io.BytesIO(csv_content.encode()), "text/csv")}
    r = client.post("/api/v1/catalog-items/upload", files=files, headers=_auth(tenant_id))
    assert r.status_code == 200, r.text
    r = client.get("/api/v1/catalog-items", headers=_auth(tenant_id))
    assert Decimal(r.json()[0]["min_price"]) == Decimal("1234.56")


# =============================================================================
# Servicio validación
# =============================================================================


def _catalog_item(ref: str, min_price: str | None = "10.00") -> CatalogItem:
    from app.models.catalog_item import normalize_reference

    return CatalogItem(
        id=uuid4(),
        tenant_id=uuid4(),
        reference=ref,
        reference_normalized=normalize_reference(ref),
        min_price=Decimal(min_price) if min_price else None,
        currency="EUR",
        active=True,
    )


def test_validate_below_min_is_blocking() -> None:
    extracted: dict[str, Any] = {
        "lineas": [
            {"referencia": "TF-75", "precio_unitario": 8.0, "cantidad": 1, "descripcion": "x"},
        ]
    }
    catalog = [_catalog_item("TF-75", "10.00")]
    result = validate_against_catalog(extracted, catalog)
    assert result["summary"]["blocking"] == 1
    assert result["lines"][0]["level"] == "blocking"
    assert "8" in result["lines"][0]["message"]


def test_validate_above_min_is_ok() -> None:
    extracted = {
        "lineas": [
            {"referencia": "TF-75", "precio_unitario": 12.0, "cantidad": 1, "descripcion": "x"},
        ]
    }
    catalog = [_catalog_item("TF-75", "10.00")]
    result = validate_against_catalog(extracted, catalog)
    assert result["summary"]["ok"] == 1
    assert result["lines"][0]["level"] == "ok"


def test_validate_unknown_reference() -> None:
    extracted = {
        "lineas": [
            {"referencia": "DESCONOCIDA", "precio_unitario": 1.0, "cantidad": 1, "descripcion": "x"},
        ]
    }
    catalog = [_catalog_item("TF-75", "10.00")]
    result = validate_against_catalog(extracted, catalog)
    assert result["summary"]["unknown"] == 1
    assert result["lines"][0]["level"] == "unknown"


def test_validate_case_insensitive_match() -> None:
    extracted = {
        "lineas": [
            {"referencia": "tf-75", "precio_unitario": 9.0, "cantidad": 1, "descripcion": "x"},
        ]
    }
    catalog = [_catalog_item("TF-75", "10.00")]
    result = validate_against_catalog(extracted, catalog)
    assert result["summary"]["blocking"] == 1


def test_validate_min_price_undefined_is_warning() -> None:
    extracted = {
        "lineas": [
            {"referencia": "TF-75", "precio_unitario": 50.0, "cantidad": 1, "descripcion": "x"},
        ]
    }
    catalog = [_catalog_item("TF-75", min_price=None)]
    result = validate_against_catalog(extracted, catalog)
    assert result["summary"]["warnings"] == 1
    assert "sin precio mínimo" in result["lines"][0]["message"]


def test_validate_no_lines() -> None:
    result = validate_against_catalog({"lineas": []}, [])
    assert result["summary"] == {"blocking": 0, "warnings": 0, "ok": 0, "unknown": 0, "total_lines": 0}
