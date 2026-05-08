"""Tests del endpoint GET /api/v1/customers (vista agregada)."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.models.document import Document, DocumentStatus, DocumentType


@pytest.fixture
def tenant_id(client: TestClient) -> UUID:
    r = client.post("/api/v1/tenants", json={"name": "Quimilock", "slug": "quimi"})
    return UUID(r.json()["id"])


def _auth(tid: UUID) -> dict[str, str]:
    return {"X-Tenant-Id": str(tid)}


def _make_pedido(
    session: Any,
    tid: UUID,
    *,
    customer_name: str,
    eu_vat: str | None = None,
    cif: str | None = None,
    total_ttc: float | None = None,
    status: DocumentStatus = DocumentStatus.APPROVED,
    erp_id: str | None = None,
) -> Document:
    extracted: dict[str, Any] = {
        "cliente": {"nombre": customer_name},
        "lineas": [],
        "totales": {"total_ttc": total_ttc} if total_ttc else {},
    }
    if eu_vat:
        extracted["cliente"]["numero_iva"] = eu_vat
    if cif:
        extracted["cliente"]["cif_nif"] = cif
    doc = Document(
        tenant_id=tid,
        pdf_key=f"{tid}/{uuid4()}.pdf",
        document_type=DocumentType.PEDIDO,
        status=status,
        extracted_json=extracted,
        erp_id=erp_id,
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


def _make_ficha(
    session: Any,
    tid: UUID,
    *,
    company_name: str,
    eu_vat: str | None = None,
    erp_id: str | None = None,
) -> Document:
    extracted: dict[str, Any] = {
        "company_name": company_name,
        "fiscal_address": {"line1": "x", "city": "y", "postal_code": "1", "country": "ES"},
    }
    if eu_vat:
        extracted["eu_vat"] = eu_vat
    doc = Document(
        tenant_id=tid,
        pdf_key=f"{tid}/{uuid4()}.pdf",
        document_type=DocumentType.FICHA_CLIENTE,
        status=DocumentStatus.APPROVED if erp_id else DocumentStatus.EXTRACTED,
        extracted_json=extracted,
        erp_id=erp_id,
        erp_url=f"http://erp.test/app/customer/{erp_id}" if erp_id else None,
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


def test_empty_tenant_returns_empty_list(client: TestClient, tenant_id: UUID) -> None:
    r = client.get("/api/v1/customers", headers=_auth(tenant_id))
    assert r.status_code == 200
    assert r.json() == {"customers": [], "total": 0}


def test_pedidos_grouped_by_vat(client: TestClient, tenant_id: UUID, session: Any) -> None:
    """Dos pedidos con el mismo VAT pero nombres distintos → 1 cliente."""
    _make_pedido(
        session,
        tenant_id,
        customer_name="RUBIX Nord",
        eu_vat="FR65320955396",
        total_ttc=100.0,
    )
    _make_pedido(
        session,
        tenant_id,
        customer_name="Rubix Nord SAS",
        eu_vat="FR 65 320 955 396",  # mismo VAT con espacios
        total_ttc=200.0,
    )

    r = client.get("/api/v1/customers", headers=_auth(tenant_id))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    c = body["customers"][0]
    assert c["pedidos_count"] == 2
    assert c["pedidos_approved_count"] == 2
    assert c["total_amount_approved"] == 300.0
    assert c["eu_vat"]  # presente
    assert c["key"].startswith("vat:")


def test_pedidos_without_vat_grouped_by_normalized_name(
    client: TestClient, tenant_id: UUID, session: Any
) -> None:
    """Sin VAT, agrupar por nombre normalizado (SAS / SARL ignorados)."""
    _make_pedido(session, tenant_id, customer_name="ATS")
    _make_pedido(session, tenant_id, customer_name="ATS S.A.S.")
    _make_pedido(session, tenant_id, customer_name="ATS SAS")

    r = client.get("/api/v1/customers", headers=_auth(tenant_id))
    body = r.json()
    assert body["total"] == 1
    assert body["customers"][0]["pedidos_count"] == 3
    assert body["customers"][0]["key"] == "name:ats"


def test_ficha_dada_de_alta_marks_customer_as_registered(
    client: TestClient, tenant_id: UUID, session: Any
) -> None:
    """Si una ficha tiene erp_id, el cliente queda como 'registered'."""
    _make_pedido(
        session,
        tenant_id,
        customer_name="ATS",
        eu_vat="FR76344020383",
        total_ttc=500.0,
    )
    _make_ficha(
        session,
        tenant_id,
        company_name="ATS S.A.S.",
        eu_vat="FR76344020383",
        erp_id="ATS",
    )

    r = client.get("/api/v1/customers", headers=_auth(tenant_id))
    body = r.json()
    assert body["total"] == 1
    c = body["customers"][0]
    assert c["is_registered_in_erp"] is True
    assert c["erp_customer_id"] == "ATS"
    assert "/app/customer/ATS" in (c["erp_customer_url"] or "")
    assert c["pedidos_count"] == 1
    assert c["fichas_count"] == 1


def test_pedidos_pushed_count_and_pending(
    client: TestClient, tenant_id: UUID, session: Any
) -> None:
    """pedidos_pushed_to_erp_count cuenta los que tienen erp_id."""
    _make_pedido(
        session,
        tenant_id,
        customer_name="ACME",
        cif="B12345678",
        total_ttc=100.0,
        erp_id="SO-1",
    )
    _make_pedido(
        session,
        tenant_id,
        customer_name="ACME",
        cif="B12345678",
        total_ttc=200.0,
        erp_id=None,
    )

    r = client.get("/api/v1/customers", headers=_auth(tenant_id))
    c = r.json()["customers"][0]
    assert c["pedidos_count"] == 2
    assert c["pedidos_pushed_to_erp_count"] == 1
    assert c["total_amount_approved"] == 300.0


def test_extracted_pedidos_dont_count_for_facturado(
    client: TestClient, tenant_id: UUID, session: Any
) -> None:
    """Solo pedidos APPROVED suman al total facturado."""
    _make_pedido(
        session,
        tenant_id,
        customer_name="ACME",
        cif="B12345678",
        total_ttc=100.0,
        status=DocumentStatus.EXTRACTED,
    )
    _make_pedido(
        session,
        tenant_id,
        customer_name="ACME",
        cif="B12345678",
        total_ttc=500.0,
        status=DocumentStatus.APPROVED,
    )

    r = client.get("/api/v1/customers", headers=_auth(tenant_id))
    c = r.json()["customers"][0]
    assert c["pedidos_count"] == 2
    assert c["pedidos_approved_count"] == 1
    assert c["total_amount_approved"] == 500.0


def test_isolation_per_tenant(client: TestClient, session: Any) -> None:
    r_a = client.post("/api/v1/tenants", json={"name": "A", "slug": "a"})
    r_b = client.post("/api/v1/tenants", json={"name": "B", "slug": "b"})
    tid_a = UUID(r_a.json()["id"])
    tid_b = UUID(r_b.json()["id"])

    _make_pedido(session, tid_a, customer_name="ACME", cif="B1")
    _make_pedido(session, tid_b, customer_name="OTRO", cif="B2")

    r = client.get("/api/v1/customers", headers=_auth(tid_a))
    body = r.json()
    assert body["total"] == 1
    assert body["customers"][0]["display_name"] == "ACME"


def test_unauthorized_without_tenant(client: TestClient) -> None:
    r = client.get("/api/v1/customers")
    assert r.status_code == 401
