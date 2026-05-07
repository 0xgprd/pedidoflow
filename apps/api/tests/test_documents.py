"""Tests endpoints documents."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.services import storage as storage_module


@pytest.fixture
def tenant_id(client: TestClient) -> UUID:
    r = client.post("/api/v1/tenants", json={"name": "Acme SA", "slug": "acme"})
    assert r.status_code == 201
    return UUID(r.json()["id"])


@pytest.fixture(autouse=True)
def isolate_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Storage local aislado por test (filesystem en tmp)."""
    storage_module.reset_storage_service()
    backend = storage_module.LocalStorageBackend(root=tmp_path / "storage")
    monkeypatch.setattr(storage_module, "_storage_singleton", backend)
    yield
    storage_module.reset_storage_service()


@pytest.fixture
def disable_celery(monkeypatch: pytest.MonkeyPatch) -> None:
    """Desactiva el dispatch real de Celery — los tests no necesitan worker."""

    class FakeAsync:
        def delay(self, *args: Any, **kwargs: Any) -> None:
            return None

    fake = FakeAsync()
    # `from app.workers.tasks import extract_document` se resuelve en el endpoint;
    # parcheamos el módulo entero para que importe nuestro fake.
    import sys
    import types

    fake_module = types.ModuleType("app.workers.tasks")
    fake_module.extract_document = fake  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.workers.tasks", fake_module)


def _auth_headers(tenant_id: UUID) -> dict[str, str]:
    return {"X-Tenant-Id": str(tenant_id)}


def test_list_documents_requires_tenant(client: TestClient) -> None:
    r = client.get("/api/v1/documents")
    assert r.status_code == 401


def test_list_documents_empty(client: TestClient, tenant_id: UUID) -> None:
    r = client.get("/api/v1/documents", headers=_auth_headers(tenant_id))
    assert r.status_code == 200
    assert r.json() == []


def test_get_unknown_document_404(client: TestClient, tenant_id: UUID) -> None:
    r = client.get(
        f"/api/v1/documents/{uuid4()}",
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 404


def test_upload_pdf_creates_pending_document(
    client: TestClient,
    tenant_id: UUID,
    disable_celery: None,
) -> None:
    pdf_bytes = b"%PDF-1.4\n%fake test content\n%%EOF\n"
    files = {"file": ("pedido.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    r = client.post(
        "/api/v1/documents",
        files=files,
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["source"] == "upload"
    assert body["original_filename"] == "pedido.pdf"
    assert body["pdf_key"].startswith(f"{tenant_id}/")
    assert body["extracted_json"] is None

    # Aparece en la lista
    r = client.get("/api/v1/documents", headers=_auth_headers(tenant_id))
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["id"] == body["id"]


def test_upload_rejects_non_pdf(
    client: TestClient,
    tenant_id: UUID,
    disable_celery: None,
) -> None:
    files = {"file": ("foo.txt", io.BytesIO(b"hello"), "text/plain")}
    r = client.post(
        "/api/v1/documents",
        files=files,
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 415


def test_upload_rejects_empty_file(
    client: TestClient,
    tenant_id: UUID,
    disable_celery: None,
) -> None:
    files = {"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")}
    r = client.post(
        "/api/v1/documents",
        files=files,
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 400


def test_documents_isolated_by_tenant(
    client: TestClient,
    tenant_id: UUID,
    disable_celery: None,
) -> None:
    # Subir doc para tenant A
    pdf_bytes = b"%PDF-1.4\nfake\n%%EOF\n"
    r = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 201
    doc_id = r.json()["id"]

    # Crear tenant B y verificar que NO ve el doc de A
    r = client.post("/api/v1/tenants", json={"name": "Other", "slug": "other"})
    assert r.status_code == 201
    other_tenant = UUID(r.json()["id"])

    r = client.get(
        f"/api/v1/documents/{doc_id}",
        headers=_auth_headers(other_tenant),
    )
    assert r.status_code == 404

    r = client.get("/api/v1/documents", headers=_auth_headers(other_tenant))
    assert r.json() == []


def test_patch_extracted_requires_extracted_status(
    client: TestClient,
    tenant_id: UUID,
    disable_celery: None,
) -> None:
    """No se puede editar un doc en pending — hay que esperar a la extracción."""
    pdf_bytes = b"%PDF-1.4\nfake\n%%EOF\n"
    r = client.post(
        "/api/v1/documents",
        files={"file": ("p.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers=_auth_headers(tenant_id),
    )
    doc_id = r.json()["id"]
    # Status sigue en pending (Celery deshabilitado en test)
    r = client.patch(
        f"/api/v1/documents/{doc_id}/extracted",
        json={"extracted_json": {"foo": "bar"}},
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 409


def test_patch_extracted_saves_corrections(
    client: TestClient,
    tenant_id: UUID,
    disable_celery: None,
    session: Any,
) -> None:
    """Edición humana sobrescribe extracted_json."""
    from app.models.document import Document, DocumentStatus

    pdf_bytes = b"%PDF-1.4\nfake\n%%EOF\n"
    r = client.post(
        "/api/v1/documents",
        files={"file": ("p.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers=_auth_headers(tenant_id),
    )
    doc_id = r.json()["id"]

    # Forzar status a "extracted" como si el worker hubiera terminado
    doc = session.get(Document, UUID(doc_id))
    doc.status = DocumentStatus.EXTRACTED
    doc.extracted_json = {"cliente": {"nombre": "WRONG"}, "lineas": []}
    session.add(doc)
    session.commit()

    new_json = {"cliente": {"nombre": "Evolis"}, "lineas": []}
    r = client.patch(
        f"/api/v1/documents/{doc_id}/extracted",
        json={"extracted_json": new_json},
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 200, r.text
    assert r.json()["extracted_json"]["cliente"]["nombre"] == "Evolis"


def test_patch_status_approve(
    client: TestClient,
    tenant_id: UUID,
    disable_celery: None,
    session: Any,
) -> None:
    from app.models.document import Document, DocumentStatus

    pdf_bytes = b"%PDF-1.4\nfake\n%%EOF\n"
    r = client.post(
        "/api/v1/documents",
        files={"file": ("p.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers=_auth_headers(tenant_id),
    )
    doc_id = r.json()["id"]

    doc = session.get(Document, UUID(doc_id))
    doc.status = DocumentStatus.EXTRACTED
    session.add(doc)
    session.commit()

    r = client.patch(
        f"/api/v1/documents/{doc_id}/status",
        json={"status": "approved"},
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"

    # Transición inválida: approved -> pending no permitido
    r = client.patch(
        f"/api/v1/documents/{doc_id}/status",
        json={"status": "pending"},
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 409


def test_filter_documents_by_status(
    client: TestClient,
    tenant_id: UUID,
    disable_celery: None,
) -> None:
    pdf_bytes = b"%PDF-1.4\nfake\n%%EOF\n"
    client.post(
        "/api/v1/documents",
        files={"file": ("p.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers=_auth_headers(tenant_id),
    )

    r = client.get(
        "/api/v1/documents?status=pending",
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = client.get(
        "/api/v1/documents?status=approved",
        headers=_auth_headers(tenant_id),
    )
    assert r.status_code == 200
    assert r.json() == []
