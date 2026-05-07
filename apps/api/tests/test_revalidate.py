"""Tests del endpoint POST /documents/revalidate."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models.catalog_item import CatalogItem, normalize_reference
from app.models.document import Document, DocumentSource, DocumentStatus, DocumentType


@pytest.fixture
def tenant_id(client: TestClient) -> UUID:
    r = client.post("/api/v1/tenants", json={"name": "Q", "slug": "q"})
    return UUID(r.json()["id"])


def _auth(t: UUID) -> dict[str, str]:
    return {"X-Tenant-Id": str(t)}


def _make_doc(
    session: Session,
    tenant_id: UUID,
    *,
    refs_with_prices: list[tuple[str, float]],
    status: DocumentStatus = DocumentStatus.EXTRACTED,
    has_blocking: bool = False,
) -> Document:
    """Crea un Document con líneas extraídas listas para validar."""
    extracted: dict[str, Any] = {
        "cliente": {"nombre": "ACME"},
        "pedido": {"numero_pedido_cliente": "PO-1"},
        "lineas": [
            {
                "referencia": ref,
                "descripcion": ref,
                "cantidad": 1,
                "unidad": "UN",
                "precio_unitario": price,
                "importe_linea": price,
            }
            for ref, price in refs_with_prices
        ],
        "totales": {"subtotal_ht": sum(p for _, p in refs_with_prices)},
        "confianza_global": "alta",
        "source_texts": {},
    }
    doc = Document(
        tenant_id=tenant_id,
        source=DocumentSource.UPLOAD,
        status=status,
        document_type=DocumentType.PEDIDO,
        pdf_key=f"{tenant_id}/test.pdf",
        original_filename="test.pdf",
        extracted_json=extracted,
        has_blocking_issues=has_blocking,
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


def _add_catalog(session: Session, tenant_id: UUID, ref: str, min_price: float | None) -> None:
    item = CatalogItem(
        tenant_id=tenant_id,
        reference=ref,
        reference_normalized=normalize_reference(ref),
        min_price=Decimal(str(min_price)) if min_price is not None else None,
        currency="EUR",
        active=True,
    )
    session.add(item)
    session.commit()


def test_revalidate_no_docs_empty_result(client: TestClient, tenant_id: UUID) -> None:
    r = client.post("/api/v1/documents/revalidate", headers=_auth(tenant_id))
    assert r.status_code == 200
    body = r.json()
    assert body["inspected"] == 0
    assert body["updated"] == 0


def test_revalidate_clears_block_after_catalog_uploaded(
    client: TestClient, tenant_id: UUID, session: Session
) -> None:
    """Doc tenía bloqueo (precio < mín), subes catálogo nuevo con min más bajo → bloqueo desaparece."""
    # Doc con line ABC-1 a precio 5 — sin catálogo, validation = unknown (no bloquea)
    doc = _make_doc(session, tenant_id, refs_with_prices=[("ABC-1", 5.0)])

    # Añadir catálogo con min_price=10 → 5 < 10 → bloquea
    _add_catalog(session, tenant_id, "ABC-1", min_price=10.0)
    r = client.post("/api/v1/documents/revalidate", headers=_auth(tenant_id))
    assert r.status_code == 200
    body = r.json()
    assert body["inspected"] == 1
    assert body["new_blocks"] == 1
    assert body["blocking_now"] == 1

    # Verificar que el doc en DB ahora marca has_blocking_issues
    session.refresh(doc)
    assert doc.has_blocking_issues is True
    assert (doc.extracted_json["validation"]["summary"]["blocking"]) == 1

    # Bajar el min_price del catálogo y re-validar → bloqueo se aclara
    item = session.exec(
        __import__("sqlmodel").select(CatalogItem).where(CatalogItem.tenant_id == tenant_id)
    ).first()
    assert item is not None
    item.min_price = Decimal("3.0")
    session.add(item)
    session.commit()

    r = client.post("/api/v1/documents/revalidate", headers=_auth(tenant_id))
    body = r.json()
    assert body["cleared_blocks"] == 1
    assert body["blocking_now"] == 0
    session.refresh(doc)
    assert doc.has_blocking_issues is False


def test_revalidate_ignores_pending_docs(
    client: TestClient, tenant_id: UUID, session: Session
) -> None:
    """Solo procesa docs ya extraídos, no los que están en pending/processing/failed."""
    _make_doc(session, tenant_id, refs_with_prices=[("X", 1.0)], status=DocumentStatus.PENDING)
    r = client.post("/api/v1/documents/revalidate", headers=_auth(tenant_id))
    assert r.json()["inspected"] == 0


def test_revalidate_only_extracted_flag(
    client: TestClient, tenant_id: UUID, session: Session
) -> None:
    """Con only_extracted=true, ignora approved/rejected; con false (default), los procesa."""
    _make_doc(session, tenant_id, refs_with_prices=[("A", 1.0)], status=DocumentStatus.APPROVED)
    _make_doc(session, tenant_id, refs_with_prices=[("B", 2.0)], status=DocumentStatus.EXTRACTED)

    r = client.post("/api/v1/documents/revalidate?only_extracted=true", headers=_auth(tenant_id))
    assert r.json()["inspected"] == 1  # solo el extracted

    r = client.post("/api/v1/documents/revalidate?only_extracted=false", headers=_auth(tenant_id))
    assert r.json()["inspected"] == 2  # extracted + approved


def test_revalidate_isolated_per_tenant(
    client: TestClient, tenant_id: UUID, session: Session
) -> None:
    other = UUID(client.post("/api/v1/tenants", json={"name": "O", "slug": "o"}).json()["id"])
    _make_doc(session, tenant_id, refs_with_prices=[("X", 1.0)])
    _make_doc(session, other, refs_with_prices=[("Y", 1.0)])

    r = client.post("/api/v1/documents/revalidate", headers=_auth(tenant_id))
    assert r.json()["inspected"] == 1
    r = client.post("/api/v1/documents/revalidate", headers=_auth(other))
    assert r.json()["inspected"] == 1
