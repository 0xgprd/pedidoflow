"""Dashboard — métricas agregadas per-tenant.

Una sola query consolidada para evitar N+1: cargamos los documents necesarios
y agregamos en Python (más simple y testeable que SQL agregado complejo).
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import load_only
from sqlmodel import Session, func, select

from app.api.deps import get_current_tenant_id
from app.core.db import get_session
from app.models.catalog_item import CatalogItem
from app.models.document import Document, DocumentStatus, DocumentType
from app.models.document_link import DocumentLink
from app.models.workflow_rule import WorkflowRule

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats")
def get_stats(
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    now = datetime.now(UTC)
    d7 = now - timedelta(days=7)
    d30 = now - timedelta(days=30)

    # Cargamos todos los documents (lite) — el tenant tiene cientos, no millones
    docs = list(
        session.exec(
            select(Document)
            .where(Document.tenant_id == tenant_id)
            .options(
                load_only(
                    Document.id,  # type: ignore[arg-type]
                    Document.status,  # type: ignore[arg-type]
                    Document.document_type,  # type: ignore[arg-type]
                    Document.original_filename,  # type: ignore[arg-type]
                    Document.created_at,  # type: ignore[arg-type]
                    Document.updated_at,  # type: ignore[arg-type]
                    Document.extracted_json,  # type: ignore[arg-type]
                )
            )
        ).all()
    )

    by_status: dict[str, int] = {s.value: 0 for s in DocumentStatus}
    by_type: dict[str, int] = {t.value: 0 for t in DocumentType}
    last_7d = last_30d = 0
    blocked_by_rules = 0
    with_validation_blocking = 0
    needs_review = 0
    approved_30d = 0
    rejected_30d = 0
    approved_total_30d = 0.0

    # Asegurar timezone-aware en created_at de DB (Postgres devuelve aware,
    # SQLite no — `tzinfo or replace` para igualar)
    def _aware(dt: datetime) -> datetime:
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)

    for d in docs:
        # status es enum nativo Postgres → tiene .value; document_type es VARCHAR → ya es str
        status_key = d.status.value if hasattr(d.status, "value") else str(d.status)
        type_key = (
            d.document_type.value if hasattr(d.document_type, "value") else str(d.document_type)
        )
        by_status[status_key] = by_status.get(status_key, 0) + 1
        by_type[type_key] = by_type.get(type_key, 0) + 1
        created = _aware(d.created_at)
        if created >= d7:
            last_7d += 1
        if created >= d30:
            last_30d += 1
        ext = d.extracted_json or {}
        if d.status == DocumentStatus.EXTRACTED:
            needs_review += 1
            if (ext.get("workflow") or {}).get("blocked"):
                blocked_by_rules += 1
            if ((ext.get("validation") or {}).get("summary") or {}).get("blocking", 0) > 0:
                with_validation_blocking += 1
        updated = _aware(d.updated_at)
        if updated >= d30:
            if d.status == DocumentStatus.APPROVED:
                approved_30d += 1
                total_ttc = (ext.get("totales") or {}).get("total_ttc")
                if isinstance(total_ttc, int | float):
                    approved_total_30d += float(total_ttc)
            elif d.status == DocumentStatus.REJECTED:
                rejected_30d += 1

    decided_30d = approved_30d + rejected_30d
    approval_rate = (approved_30d / decided_30d) if decided_30d > 0 else None

    # Linking: pedidos vinculados
    pedidos_count = by_type["pedido"]
    linked_orders = (
        session.exec(
            select(func.count(DocumentLink.id)).where(DocumentLink.tenant_id == tenant_id)  # type: ignore[arg-type]
        ).first()
        or 0
    )
    pedidos_with_offer = int(linked_orders) if linked_orders else 0
    pedidos_without_offer = max(pedidos_count - pedidos_with_offer, 0)

    # Reglas
    rules = list(
        session.exec(select(WorkflowRule).where(WorkflowRule.tenant_id == tenant_id)).all()
    )
    active_rules = [r for r in rules if r.enabled]
    top_rules = sorted(active_rules, key=lambda r: r.hits, reverse=True)[:5]

    # Catálogo
    catalog_count = (
        session.exec(
            select(func.count(CatalogItem.id)).where(CatalogItem.tenant_id == tenant_id)  # type: ignore[arg-type]
        ).first()
        or 0
    )
    catalog_no_min = (
        session.exec(
            select(func.count(CatalogItem.id)).where(  # type: ignore[arg-type]
                CatalogItem.tenant_id == tenant_id,
                CatalogItem.min_price.is_(None),  # type: ignore[union-attr]
            )
        ).first()
        or 0
    )

    # Documentos recientes (últimos 10)
    recent = sorted(docs, key=lambda d: _aware(d.created_at), reverse=True)[:10]

    return {
        "documents": {
            "total": len(docs),
            "by_status": by_status,
            "by_type": by_type,
            "last_7d": last_7d,
            "last_30d": last_30d,
        },
        "needs_review": {
            "count": needs_review,
            "blocked_by_rules": blocked_by_rules,
            "with_validation_blocking": with_validation_blocking,
        },
        "approval_rate": {
            "approved_30d": approved_30d,
            "rejected_30d": rejected_30d,
            "rate": approval_rate,
        },
        "linking": {
            "pedidos_with_offer": pedidos_with_offer,
            "pedidos_without_offer": pedidos_without_offer,
        },
        "amounts": {
            "approved_total_30d": round(approved_total_30d, 2),
            "currency": "EUR",
        },
        "rules": {
            "active_count": len(active_rules),
            "total_count": len(rules),
            "top_5": [{"id": str(r.id), "name": r.name, "hits": r.hits} for r in top_rules],
        },
        "catalog": {
            "items_count": int(catalog_count),
            "items_without_min_price": int(catalog_no_min),
        },
        "recent_documents": [
            {
                "id": str(d.id),
                "original_filename": d.original_filename,
                "status": d.status.value if hasattr(d.status, "value") else str(d.status),
                "document_type": d.document_type.value
                if hasattr(d.document_type, "value")
                else str(d.document_type),
                "created_at": d.created_at.isoformat(),
            }
            for d in recent
        ],
    }
