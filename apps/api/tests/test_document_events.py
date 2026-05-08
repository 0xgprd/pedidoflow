"""Tests del audit log: helper record_event + endpoint /events.

Verifica que las acciones humanas (aprobar, empujar al ERP, dar de alta,
editar...) generan rows en document_events, mientras que las acciones de
la IA NO generan eventos.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.models.document import Document, DocumentStatus, DocumentType
from app.models.document_event import DocumentEvent, DocumentEventType


@pytest.fixture
def tenant_id(client: TestClient) -> UUID:
    r = client.post("/api/v1/tenants", json={"name": "Q", "slug": "q"})
    return UUID(r.json()["id"])


def _auth(tid: UUID) -> dict[str, str]:
    return {"X-Tenant-Id": str(tid)}


def _make_doc(
    session: Any,
    tid: UUID,
    *,
    doc_type: DocumentType = DocumentType.PEDIDO,
    status: DocumentStatus = DocumentStatus.EXTRACTED,
    extracted: dict[str, Any] | None = None,
) -> Document:
    doc = Document(
        tenant_id=tid,
        pdf_key=f"{tid}/{uuid4()}.pdf",
        document_type=doc_type,
        status=status,
        extracted_json=extracted or {"cliente": {"nombre": "ACME"}, "lineas": []},
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


def _events_for(session: Any, doc_id: UUID) -> list[DocumentEvent]:
    from sqlmodel import select

    return list(
        session.exec(
            select(DocumentEvent)
            .where(DocumentEvent.document_id == doc_id)
            .order_by(DocumentEvent.created_at.asc())  # type: ignore[union-attr]
        ).all()
    )


# =============================================================================
# Endpoint /events — vacío y filtros
# =============================================================================


def test_events_endpoint_returns_empty_when_no_actions(
    client: TestClient, tenant_id: UUID, session: Any
) -> None:
    doc = _make_doc(session, tenant_id)
    r = client.get(f"/api/v1/documents/{doc.id}/events", headers=_auth(tenant_id))
    assert r.status_code == 200
    assert r.json() == []


def test_events_endpoint_404_for_unknown(client: TestClient, tenant_id: UUID) -> None:
    r = client.get(f"/api/v1/documents/{uuid4()}/events", headers=_auth(tenant_id))
    assert r.status_code == 404


def test_events_isolated_per_tenant(client: TestClient, session: Any) -> None:
    r_a = client.post("/api/v1/tenants", json={"name": "A", "slug": "a"})
    r_b = client.post("/api/v1/tenants", json={"name": "B", "slug": "b"})
    tid_a = UUID(r_a.json()["id"])
    tid_b = UUID(r_b.json()["id"])

    doc_b = _make_doc(session, tid_b)
    r = client.get(f"/api/v1/documents/{doc_b.id}/events", headers=_auth(tid_a))
    assert r.status_code == 404


# =============================================================================
# Acciones humanas → generan eventos
# =============================================================================


def test_patch_status_approved_records_event(
    client: TestClient, tenant_id: UUID, session: Any
) -> None:
    doc = _make_doc(session, tenant_id)
    r = client.patch(
        f"/api/v1/documents/{doc.id}/status",
        json={"status": "approved"},
        headers=_auth(tenant_id),
    )
    assert r.status_code == 200
    events = _events_for(session, doc.id)
    assert len(events) == 1
    assert events[0].event_type == DocumentEventType.APPROVED
    assert events[0].event_data["from_status"] == "extracted"
    assert events[0].event_data["to_status"] == "approved"


def test_patch_status_rejected_records_event_with_reason(
    client: TestClient, tenant_id: UUID, session: Any
) -> None:
    doc = _make_doc(session, tenant_id)
    r = client.patch(
        f"/api/v1/documents/{doc.id}/status",
        json={"status": "rejected", "reason": "precio mal"},
        headers=_auth(tenant_id),
    )
    assert r.status_code == 200
    events = _events_for(session, doc.id)
    assert len(events) == 1
    assert events[0].event_type == DocumentEventType.REJECTED
    assert events[0].event_data["reason"] == "precio mal"


def test_reopen_from_approved_records_event(
    client: TestClient, tenant_id: UUID, session: Any
) -> None:
    """approved → extracted → evento REOPENED (no APPROVED ni nada raro)."""
    doc = _make_doc(session, tenant_id, status=DocumentStatus.APPROVED)
    r = client.patch(
        f"/api/v1/documents/{doc.id}/status",
        json={"status": "extracted"},
        headers=_auth(tenant_id),
    )
    assert r.status_code == 200
    events = _events_for(session, doc.id)
    types = [e.event_type for e in events]
    assert DocumentEventType.REOPENED in types


def test_patch_extracted_records_event(client: TestClient, tenant_id: UUID, session: Any) -> None:
    doc = _make_doc(session, tenant_id)
    new_json = {"cliente": {"nombre": "EDITED"}, "lineas": []}
    r = client.patch(
        f"/api/v1/documents/{doc.id}/extracted",
        json={"extracted_json": new_json},
        headers=_auth(tenant_id),
    )
    assert r.status_code == 200
    events = _events_for(session, doc.id)
    assert any(e.event_type == DocumentEventType.EXTRACTED_EDITED for e in events)


def test_patch_document_type_records_event(
    client: TestClient, tenant_id: UUID, session: Any
) -> None:
    doc = _make_doc(session, tenant_id, doc_type=DocumentType.DESCONOCIDO)
    r = client.patch(
        f"/api/v1/documents/{doc.id}/type",
        json={"document_type": "pedido"},
        headers=_auth(tenant_id),
    )
    assert r.status_code == 200
    events = _events_for(session, doc.id)
    type_change_events = [e for e in events if e.event_type == DocumentEventType.TYPE_CHANGED]
    assert len(type_change_events) == 1
    assert type_change_events[0].event_data["from"] == "desconocido"
    assert type_change_events[0].event_data["to"] == "pedido"


def test_patch_document_type_no_event_when_unchanged(
    client: TestClient, tenant_id: UUID, session: Any
) -> None:
    """Si el tipo es el mismo, no se registra evento (no hubo cambio)."""
    doc = _make_doc(session, tenant_id, doc_type=DocumentType.PEDIDO)
    r = client.patch(
        f"/api/v1/documents/{doc.id}/type",
        json={"document_type": "pedido"},
        headers=_auth(tenant_id),
    )
    assert r.status_code == 200
    events = _events_for(session, doc.id)
    assert events == []


# =============================================================================
# Eventos vienen ordenados ascendente
# =============================================================================


def test_events_returned_in_chronological_order(
    client: TestClient, tenant_id: UUID, session: Any
) -> None:
    doc = _make_doc(session, tenant_id)
    # Hacemos 2 acciones consecutivas
    client.patch(
        f"/api/v1/documents/{doc.id}/status",
        json={"status": "approved"},
        headers=_auth(tenant_id),
    )
    client.patch(
        f"/api/v1/documents/{doc.id}/status",
        json={"status": "extracted"},
        headers=_auth(tenant_id),
    )

    r = client.get(f"/api/v1/documents/{doc.id}/events", headers=_auth(tenant_id))
    events = r.json()
    assert len(events) == 2
    # Primero APPROVED, después REOPENED
    assert events[0]["event_type"] == "approved"
    assert events[1]["event_type"] == "reopened"


# =============================================================================
# Schema de respuesta — campos esperados por la UI
# =============================================================================


def test_event_response_has_expected_fields(
    client: TestClient, tenant_id: UUID, session: Any
) -> None:
    doc = _make_doc(session, tenant_id)
    client.patch(
        f"/api/v1/documents/{doc.id}/status",
        json={"status": "approved"},
        headers=_auth(tenant_id),
    )
    r = client.get(f"/api/v1/documents/{doc.id}/events", headers=_auth(tenant_id))
    event = r.json()[0]
    # Campos que la UI necesita para renderizar el timeline
    assert "id" in event
    assert "event_type" in event
    assert "actor_email" in event
    assert "actor_label" in event
    assert "event_data" in event
    assert "created_at" in event
