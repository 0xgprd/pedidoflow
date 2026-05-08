"""Tests del endpoint POST /api/v1/documents/{id}/register-customer."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.models.document import Document, DocumentStatus, DocumentType
from app.services.erp import (
    AuthError,
    CanonicalCustomerRegistration,
    CustomerRegistrationResult,
    PushResult,
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
# Fake adapter — captura registrations y permite simular errores
# =============================================================================


class _FakeAdapter:
    name = "fake"

    def __init__(self, *, raises: Exception | None = None) -> None:
        self.raises = raises
        self.registrations: list[CanonicalCustomerRegistration] = []

    def health_check(self) -> bool:
        return True

    def push_sales_order(self, order: CanonicalSalesOrder) -> PushResult:
        return PushResult(erp_id="SO-X", erp_url=None, status="draft")

    def push_delivery_note(self, note: CanonicalDeliveryNote) -> PushResult:
        raise NotImplementedError

    def push_invoice(self, invoice: CanonicalInvoice) -> PushResult:
        raise NotImplementedError

    def register_customer(
        self, registration: CanonicalCustomerRegistration
    ) -> CustomerRegistrationResult:
        self.registrations.append(registration)
        if self.raises:
            raise self.raises
        return CustomerRegistrationResult(
            erp_customer_id="ATS",
            erp_customer_url="http://erp.test/app/customer/ATS",
            addresses_created=2,
            contacts_created=2,
        )


@pytest.fixture
def fake_adapter(monkeypatch: pytest.MonkeyPatch) -> _FakeAdapter:
    fake = _FakeAdapter()
    import app.api.documents as docs_module

    monkeypatch.setattr(docs_module, "get_erp_adapter", lambda: fake)
    return fake


@pytest.fixture
def fake_adapter_factory(monkeypatch: pytest.MonkeyPatch):
    def _setup(*, raises: Exception | None = None) -> _FakeAdapter:
        fake = _FakeAdapter(raises=raises)
        import app.api.documents as docs_module

        monkeypatch.setattr(docs_module, "get_erp_adapter", lambda: fake)
        return fake

    return _setup


# =============================================================================
# Helper: doc tipo ficha extraído
# =============================================================================


def _make_extracted_ficha(session: Any, tenant_id: UUID) -> UUID:
    """Crea un Document tipo ficha_cliente con extracted_json realista."""
    doc = Document(
        tenant_id=tenant_id,
        pdf_key=f"{tenant_id}/{uuid4()}.pdf",
        original_filename="QUIMILOCK Customer Registration Form_Fr.pdf",
        document_type=DocumentType.FICHA_CLIENTE,
        status=DocumentStatus.EXTRACTED,
        extracted_json={
            "company_name": "ATS",
            "eu_vat": "FR76344020383",
            "fiscal_address": {
                "line1": "Z.I. Des Agriers",
                "city": "Angouleme",
                "postal_code": "16000",
                "country": "France",
            },
            "tax_category": "eu_intracom",
        },
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc.id


def _ficha_payload() -> dict[str, Any]:
    """Payload realista que envía el frontend tras revisar la ficha."""
    return {
        "company_name": "ATS",
        "eu_vat": "FR76344020383",
        "supplier_number_in_customer_system": "QML-001",
        "fiscal_address": {
            "line1": "Z.I. Des Agriers",
            "city": "Angouleme",
            "postal_code": "16000",
            "country": "France",
        },
        "main_phone": "+33 545913737",
        "main_email": "accueil@angouleme-ts.fr",
        "contacts": [
            {
                "name": "Cédric Chabanne",
                "role": "Acheteur",
                "phone": "+33 545913737",
                "email": "cchabanne@angouleme-ts.fr",
            },
            {"name": "Delphine Andreo", "role": "Comptable"},
        ],
        "tax_category": "eu_intracom",
        "payment_terms": "Virement bancaire 30 jours",
        "preferred_language": "fr",
        "signed_by_name": "Cédric Chabanne",
        "signed_by_role": "Directeur",
        "signature_date": "2026-04-15",
    }


# =============================================================================
# Happy path
# =============================================================================


def test_register_customer_happy_path(
    client: TestClient, tenant_id: UUID, fake_adapter: _FakeAdapter, session: Any
) -> None:
    doc_id = _make_extracted_ficha(session, tenant_id)

    r = client.post(
        f"/api/v1/documents/{doc_id}/register-customer",
        json=_ficha_payload(),
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["erp_adapter"] == "fake"
    assert body["erp_id"] == "ATS"
    assert body["erp_url"] == "http://erp.test/app/customer/ATS"
    assert body["status"] == "approved"
    assert body["erp_pushed_at"] is not None
    assert body["erp_push_error"] is None

    # Adapter recibió la conversión correcta
    assert len(fake_adapter.registrations) == 1
    reg = fake_adapter.registrations[0]
    assert reg.company_name == "ATS"
    assert reg.eu_vat == "FR76344020383"
    assert reg.tax_category == "eu_intracom"
    assert len(reg.contacts) == 2
    assert reg.fiscal_address.country == "France"
    assert reg.signed_by_name == "Cédric Chabanne"


# =============================================================================
# Validaciones de precondiciones
# =============================================================================


def test_register_unknown_document_returns_404(
    client: TestClient, tenant_id: UUID, fake_adapter: _FakeAdapter
) -> None:
    r = client.post(
        f"/api/v1/documents/{uuid4()}/register-customer",
        json=_ficha_payload(),
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 404


def test_register_pedido_returns_409(
    client: TestClient, tenant_id: UUID, fake_adapter: _FakeAdapter, session: Any
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
        f"/api/v1/documents/{doc.id}/register-customer",
        json=_ficha_payload(),
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 409
    assert "fichas" in r.json()["detail"].lower()


def test_register_already_registered_returns_409(
    client: TestClient, tenant_id: UUID, fake_adapter: _FakeAdapter, session: Any
) -> None:
    """Si el doc ya tiene erp_id, no se vuelve a dar de alta."""
    doc_id = _make_extracted_ficha(session, tenant_id)
    doc = session.get(Document, doc_id)
    doc.erp_id = "ATS-OLD"
    session.add(doc)
    session.commit()

    r = client.post(
        f"/api/v1/documents/{doc_id}/register-customer",
        json=_ficha_payload(),
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 409
    assert "ATS-OLD" in r.json()["detail"]


# =============================================================================
# Sin ERP configurado
# =============================================================================


def test_register_when_no_erp_configured_returns_503(
    client: TestClient, tenant_id: UUID, monkeypatch: pytest.MonkeyPatch, session: Any
) -> None:
    import app.api.documents as docs_module

    monkeypatch.setattr(docs_module, "get_erp_adapter", lambda: None)

    doc_id = _make_extracted_ficha(session, tenant_id)
    r = client.post(
        f"/api/v1/documents/{doc_id}/register-customer",
        json=_ficha_payload(),
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 503


# =============================================================================
# Errores del adapter
# =============================================================================


def test_register_validation_error_returns_422_and_persists(
    client: TestClient, tenant_id: UUID, fake_adapter_factory, session: Any
) -> None:
    fake_adapter_factory(raises=ERPValidationError("duplicado"))
    doc_id = _make_extracted_ficha(session, tenant_id)

    r = client.post(
        f"/api/v1/documents/{doc_id}/register-customer",
        json=_ficha_payload(),
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 422
    doc = session.get(Document, doc_id)
    session.refresh(doc)
    assert doc.erp_push_error is not None
    assert "duplicado" in doc.erp_push_error.lower()


def test_register_auth_error_returns_502(
    client: TestClient, tenant_id: UUID, fake_adapter_factory, session: Any
) -> None:
    fake_adapter_factory(raises=AuthError("bad token"))
    doc_id = _make_extracted_ficha(session, tenant_id)

    r = client.post(
        f"/api/v1/documents/{doc_id}/register-customer",
        json=_ficha_payload(),
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 502


# =============================================================================
# Validaciones del payload
# =============================================================================


def test_register_with_bad_payload_returns_422(
    client: TestClient, tenant_id: UUID, fake_adapter: _FakeAdapter, session: Any
) -> None:
    """Payload sin company_name → 422 de FastAPI."""
    doc_id = _make_extracted_ficha(session, tenant_id)
    bad_payload = _ficha_payload()
    del bad_payload["company_name"]

    r = client.post(
        f"/api/v1/documents/{doc_id}/register-customer",
        json=bad_payload,
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 422


def test_register_with_invalid_signature_date_returns_422(
    client: TestClient, tenant_id: UUID, fake_adapter: _FakeAdapter, session: Any
) -> None:
    """signature_date inválida → 422."""
    doc_id = _make_extracted_ficha(session, tenant_id)
    bad_payload = _ficha_payload()
    bad_payload["signature_date"] = "no-es-fecha"

    r = client.post(
        f"/api/v1/documents/{doc_id}/register-customer",
        json=bad_payload,
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 422


# =============================================================================
# Tenant isolation
# =============================================================================


def test_register_other_tenant_doc_returns_404(
    client: TestClient, fake_adapter: _FakeAdapter, session: Any
) -> None:
    r_a = client.post("/api/v1/tenants", json={"name": "A", "slug": "a"})
    r_b = client.post("/api/v1/tenants", json={"name": "B", "slug": "b"})
    tid_a = UUID(r_a.json()["id"])
    tid_b = UUID(r_b.json()["id"])

    doc_id_b = _make_extracted_ficha(session, tid_b)

    r = client.post(
        f"/api/v1/documents/{doc_id_b}/register-customer",
        json=_ficha_payload(),
        headers=_auth_headers(tid_a),
    )
    assert r.status_code == 404
