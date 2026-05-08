"""Tests del endpoint POST /api/v1/documents/{id}/push-to-erp.

Mockeamos `get_erp_adapter` con un adapter en memoria — los tests del
ERPNextAdapter real (httpx.MockTransport) están en test_erpnext_adapter.py.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.models.document import Document, DocumentStatus, DocumentType
from app.services.erp import (
    AuthError,
    ERPAdapterError,
    PushResult,
    TransientError,
)
from app.services.erp import (
    NotFoundError as ERPNotFoundError,
)
from app.services.erp import (
    ValidationError as ERPValidationError,
)
from app.services.erp.canonical import (
    CanonicalDeliveryNote,
    CanonicalInvoice,
    CanonicalSalesOrder,
)


@pytest.fixture
def tenant_id(client: TestClient) -> UUID:
    r = client.post("/api/v1/tenants", json={"name": "Acme SA", "slug": "acme"})
    assert r.status_code == 201
    return UUID(r.json()["id"])


def _auth_headers(tenant_id: UUID) -> dict[str, str]:
    return {"X-Tenant-Id": str(tenant_id)}


# =============================================================================
# Fake adapter en memoria (para no tocar ERPNext real)
# =============================================================================


class _FakeAdapter:
    """Capturamos los push y devolvemos PushResult fijo o lanzamos lo que se diga."""

    name = "fake"

    def __init__(self, *, raises: Exception | None = None) -> None:
        self.raises = raises
        self.calls: list[CanonicalSalesOrder] = []

    def health_check(self) -> bool:
        return True

    def push_sales_order(self, order: CanonicalSalesOrder) -> PushResult:
        self.calls.append(order)
        if self.raises:
            raise self.raises
        return PushResult(
            erp_id="SAL-ORD-FAKE-001",
            erp_url="http://erp.test/app/sales-order/SAL-ORD-FAKE-001",
            status="draft",
        )

    def push_delivery_note(self, note: CanonicalDeliveryNote) -> PushResult:
        raise NotImplementedError

    def push_invoice(self, invoice: CanonicalInvoice) -> PushResult:
        raise NotImplementedError


@pytest.fixture
def fake_adapter(monkeypatch: pytest.MonkeyPatch) -> _FakeAdapter:
    fake = _FakeAdapter()
    # El endpoint llama get_erp_adapter() del módulo erp; parcheamos ahí donde se importa
    import app.api.documents as docs_module

    monkeypatch.setattr(docs_module, "get_erp_adapter", lambda: fake)
    return fake


@pytest.fixture
def fake_adapter_factory(monkeypatch: pytest.MonkeyPatch):
    """Permite parametrizar la excepción que el adapter lanzará."""

    def _setup(*, raises: Exception | None = None) -> _FakeAdapter:
        fake = _FakeAdapter(raises=raises)
        import app.api.documents as docs_module

        monkeypatch.setattr(docs_module, "get_erp_adapter", lambda: fake)
        return fake

    return _setup


# =============================================================================
# Helper: doc aprobado con extracted_json válido
# =============================================================================


def _make_approved_pedido(session: Any, tenant_id: UUID) -> UUID:
    extracted: dict[str, Any] = {
        "cliente": {"nombre": "ATS", "numero_iva": "FR76344020383"},
        "pedido": {"numero_pedido_cliente": "CF26072", "fecha_pedido": "2026-04-23"},
        "lineas": [
            {
                "referencia": "T1-400",
                "descripcion": "T1-400 BLEU",
                "cantidad": 35,
                "precio_unitario": 10.9,
                "importe_linea": 381.5,
            },
        ],
        "totales": {"subtotal_ht": 381.5, "total_ttc": 461.62},
    }
    doc = Document(
        tenant_id=tenant_id,
        pdf_key=f"{tenant_id}/{uuid4()}.pdf",
        original_filename="cf26072.pdf",
        document_type=DocumentType.PEDIDO,
        status=DocumentStatus.APPROVED,
        extracted_json=extracted,
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc.id


# =============================================================================
# Happy path
# =============================================================================


def test_push_pedido_approved_returns_200_with_erp_fields(
    client: TestClient,
    tenant_id: UUID,
    fake_adapter: _FakeAdapter,
    session: Any,
) -> None:
    doc_id = _make_approved_pedido(session, tenant_id)

    r = client.post(
        f"/api/v1/documents/{doc_id}/push-to-erp",
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["erp_adapter"] == "fake"
    assert body["erp_id"] == "SAL-ORD-FAKE-001"
    assert "SAL-ORD-FAKE-001" in body["erp_url"]
    assert body["erp_pushed_at"] is not None
    assert body["erp_push_error"] is None

    # El adapter recibió la conversión canonical correcta
    assert len(fake_adapter.calls) == 1
    sent = fake_adapter.calls[0]
    assert sent.customer.name == "ATS"
    assert sent.customer.eu_vat == "FR76344020383"
    assert sent.customer_po_number == "CF26072"
    assert len(sent.lines) == 1


def test_re_pushing_creates_new_so_each_time(
    client: TestClient,
    tenant_id: UUID,
    fake_adapter: _FakeAdapter,
    session: Any,
) -> None:
    """Empujar 2 veces el mismo doc → adapter llamado 2 veces (no idempotente)."""
    doc_id = _make_approved_pedido(session, tenant_id)
    headers = _auth_headers(tenant_id)
    assert (
        client.post(f"/api/v1/documents/{doc_id}/push-to-erp", headers=headers).status_code == 200
    )
    assert (
        client.post(f"/api/v1/documents/{doc_id}/push-to-erp", headers=headers).status_code == 200
    )
    assert len(fake_adapter.calls) == 2


# =============================================================================
# Validaciones de precondiciones
# =============================================================================


def test_push_unknown_document_returns_404(
    client: TestClient, tenant_id: UUID, fake_adapter: _FakeAdapter
) -> None:
    r = client.post(
        f"/api/v1/documents/{uuid4()}/push-to-erp",
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 404


def test_push_oferta_returns_409(
    client: TestClient,
    tenant_id: UUID,
    fake_adapter: _FakeAdapter,
    session: Any,
) -> None:
    doc = Document(
        tenant_id=tenant_id,
        pdf_key=f"{tenant_id}/{uuid4()}.pdf",
        document_type=DocumentType.OFERTA,
        status=DocumentStatus.APPROVED,
        extracted_json={"cliente": {"nombre": "x"}, "lineas": []},
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)

    r = client.post(
        f"/api/v1/documents/{doc.id}/push-to-erp",
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 409
    assert "pedidos" in r.json()["detail"].lower()


def test_push_extracted_not_approved_returns_409(
    client: TestClient,
    tenant_id: UUID,
    fake_adapter: _FakeAdapter,
    session: Any,
) -> None:
    doc = Document(
        tenant_id=tenant_id,
        pdf_key=f"{tenant_id}/{uuid4()}.pdf",
        document_type=DocumentType.PEDIDO,
        status=DocumentStatus.EXTRACTED,
        extracted_json={"cliente": {"nombre": "x"}, "lineas": []},
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)

    r = client.post(
        f"/api/v1/documents/{doc.id}/push-to-erp",
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 409
    assert "approved" in r.json()["detail"].lower()


def test_push_pedido_with_empty_extracted_returns_422(
    client: TestClient,
    tenant_id: UUID,
    fake_adapter: _FakeAdapter,
    session: Any,
) -> None:
    """Pedido approved pero sin líneas → mapping falla → 422."""
    doc = Document(
        tenant_id=tenant_id,
        pdf_key=f"{tenant_id}/{uuid4()}.pdf",
        document_type=DocumentType.PEDIDO,
        status=DocumentStatus.APPROVED,
        extracted_json={"cliente": {"nombre": "X"}, "lineas": []},
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)

    r = client.post(
        f"/api/v1/documents/{doc.id}/push-to-erp",
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 422


# =============================================================================
# ERP no configurado
# =============================================================================


def test_push_when_no_erp_configured_returns_503(
    client: TestClient,
    tenant_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
    session: Any,
) -> None:
    import app.api.documents as docs_module

    monkeypatch.setattr(docs_module, "get_erp_adapter", lambda: None)

    doc_id = _make_approved_pedido(session, tenant_id)
    r = client.post(
        f"/api/v1/documents/{doc_id}/push-to-erp",
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 503
    assert "ERPNEXT_BASE_URL" in r.json()["detail"]


# =============================================================================
# Errores del adapter → mapeo a HTTP correcto
# =============================================================================


def test_auth_error_returns_502(
    client: TestClient, tenant_id: UUID, fake_adapter_factory, session: Any
) -> None:
    fake_adapter_factory(raises=AuthError("bad token"))
    doc_id = _make_approved_pedido(session, tenant_id)

    r = client.post(
        f"/api/v1/documents/{doc_id}/push-to-erp",
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 502


def test_validation_error_returns_422_and_persists_error(
    client: TestClient, tenant_id: UUID, fake_adapter_factory, session: Any
) -> None:
    fake_adapter_factory(raises=ERPValidationError("freight account missing"))
    doc_id = _make_approved_pedido(session, tenant_id)

    r = client.post(
        f"/api/v1/documents/{doc_id}/push-to-erp",
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 422
    # erp_push_error guardado en DB
    doc = session.get(Document, doc_id)
    session.refresh(doc)
    assert doc.erp_push_error is not None
    assert "freight" in doc.erp_push_error.lower()


def test_not_found_error_returns_422(
    client: TestClient, tenant_id: UUID, fake_adapter_factory, session: Any
) -> None:
    fake_adapter_factory(raises=ERPNotFoundError("customer not found"))
    doc_id = _make_approved_pedido(session, tenant_id)

    r = client.post(
        f"/api/v1/documents/{doc_id}/push-to-erp",
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 422


def test_transient_error_returns_503(
    client: TestClient, tenant_id: UUID, fake_adapter_factory, session: Any
) -> None:
    fake_adapter_factory(raises=TransientError("upstream timeout"))
    doc_id = _make_approved_pedido(session, tenant_id)

    r = client.post(
        f"/api/v1/documents/{doc_id}/push-to-erp",
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 503


def test_generic_adapter_error_returns_502(
    client: TestClient, tenant_id: UUID, fake_adapter_factory, session: Any
) -> None:
    fake_adapter_factory(raises=ERPAdapterError("unexpected"))
    doc_id = _make_approved_pedido(session, tenant_id)

    r = client.post(
        f"/api/v1/documents/{doc_id}/push-to-erp",
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 502


# =============================================================================
# Tenant isolation
# =============================================================================


def test_push_other_tenant_doc_returns_404(
    client: TestClient,
    fake_adapter: _FakeAdapter,
    session: Any,
) -> None:
    """Tenant A intenta empujar un doc del tenant B → 404 (sin filtración)."""
    r_a = client.post("/api/v1/tenants", json={"name": "A", "slug": "a"})
    r_b = client.post("/api/v1/tenants", json={"name": "B", "slug": "b"})
    tid_a = UUID(r_a.json()["id"])
    tid_b = UUID(r_b.json()["id"])

    doc_id_b = _make_approved_pedido(session, tid_b)

    r = client.post(
        f"/api/v1/documents/{doc_id_b}/push-to-erp",
        headers=_auth_headers(tid_a),
    )
    assert r.status_code == 404
