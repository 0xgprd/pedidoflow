"""Endpoints de Documents — pedidos PDF en el pipeline de extracción."""

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import load_only
from sqlmodel import Session, select

from app.api.deps import get_current_tenant_id
from app.core.db import get_session
from app.core.logging import get_logger
from app.models.catalog_item import CatalogItem
from app.models.document import (
    Document,
    DocumentListItem,
    DocumentRead,
    DocumentSource,
    DocumentStatus,
    DocumentType,
)
from app.models.document_link import DocumentLink, DocumentLinkRead, MatchStrategy
from app.models.workflow_rule import WorkflowRule
from app.services.classification import classify_document
from app.services.erp import (
    AuthError,
    CustomerNotRegisteredError,
    ERPAdapterError,
    TransientError,
    extracted_to_sales_order,
    get_erp_adapter,
)
from app.services.erp import (
    NotFoundError as ERPNotFoundError,
)
from app.services.erp import (
    ValidationError as ERPValidationError,
)
from app.services.matching import compare_order_vs_offer, find_matching_offer
from app.services.rules_engine import evaluate_rules
from app.services.storage import get_storage_service
from app.services.validation import validate_against_catalog

log = get_logger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])

MAX_PDF_BYTES = 20 * 1024 * 1024  # 20 MB
ALLOWED_CONTENT_TYPES = {"application/pdf"}


@router.get("", response_model=list[DocumentListItem])
def list_documents(
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
    status_filter: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    type_filter: Annotated[DocumentType | None, Query(alias="type")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DocumentListItem]:
    """Lista paginada de documentos del tenant actual.

    Devuelve `DocumentListItem` (sin `extracted_json` ni `ocr_result`) para
    que la bandeja no descargue 10-50× más datos de los que necesita.
    Para el detalle completo usa `GET /documents/{id}`.

    Calcula on-the-fly `has_offer_link` para pedidos (1 query extra al tenant).
    """
    query = select(Document).where(Document.tenant_id == tenant_id)
    if status_filter is not None:
        query = query.where(Document.status == status_filter)
    if type_filter is not None:
        query = query.where(Document.document_type == type_filter)
    query = query.order_by(Document.created_at.desc()).offset(offset).limit(limit)  # type: ignore[attr-defined]
    docs = list(session.exec(query).all())

    # Set de pedidos que tienen oferta vinculada (1 query, in-memory join)
    linked_order_ids: set[UUID] = set(
        session.exec(
            select(DocumentLink.order_document_id).where(DocumentLink.tenant_id == tenant_id)
        ).all()
    )

    items: list[DocumentListItem] = []
    for d in docs:
        # `has_offer_link` solo aplica a pedidos. None = N/A.
        is_pedido = d.document_type == DocumentType.PEDIDO or str(d.document_type) == "pedido"
        has_link = d.id in linked_order_ids if is_pedido else None
        items.append(
            DocumentListItem(
                id=d.id,
                tenant_id=d.tenant_id,
                source=d.source,
                status=d.status,
                document_type=d.document_type,
                original_filename=d.original_filename,
                source_email=d.source_email,
                extraction_error=d.extraction_error,
                has_blocking_issues=d.has_blocking_issues,
                has_discrepancies=d.has_discrepancies,
                has_offer_link=has_link,
                erp_id=d.erp_id,
                created_at=d.created_at,
                updated_at=d.updated_at,
                processed_at=d.processed_at,
                email_received_at=d.email_received_at,
            )
        )
    return items


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(
    document_id: UUID,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> Document:
    """Detalle de un documento.

    Excluye `ocr_result` y `raw_text` del SELECT (pueden ser 50-200KB cada uno).
    Si en el futuro hace falta exponerlos, hacer endpoint dedicado.
    """
    query = (
        select(Document)
        .where(Document.id == document_id)
        .options(
            load_only(
                Document.id,  # type: ignore[arg-type]
                Document.tenant_id,  # type: ignore[arg-type]
                Document.source,  # type: ignore[arg-type]
                Document.status,  # type: ignore[arg-type]
                Document.pdf_key,  # type: ignore[arg-type]
                Document.original_filename,  # type: ignore[arg-type]
                Document.source_email,  # type: ignore[arg-type]
                Document.extracted_json,  # type: ignore[arg-type]
                Document.extraction_error,  # type: ignore[arg-type]
                Document.created_at,  # type: ignore[arg-type]
                Document.updated_at,  # type: ignore[arg-type]
                Document.processed_at,  # type: ignore[arg-type]
            )
        )
    )
    doc = session.exec(query).first()
    if doc is None or doc.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return doc


@router.get("/{document_id}/pdf")
def get_document_pdf(
    document_id: UUID,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    """Devuelve el contenido binario del PDF (con tenant check)."""
    doc = session.get(Document, document_id)
    if doc is None or doc.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    storage = get_storage_service()
    try:
        pdf_bytes = storage.download_pdf(doc.pdf_key)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"PDF storage object missing: {doc.pdf_key}",
        ) from e

    filename = doc.original_filename or f"{doc.id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post(
    "",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
    file: Annotated[UploadFile, File(description="PDF del pedido")],
) -> Document:
    """Sube un PDF, lo guarda en storage y crea Document `pending`.

    Encola tarea Celery para extracción IA (asíncrona).
    """
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Only PDF allowed (got {file.content_type})",
        )

    body = await file.read()
    if len(body) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    if len(body) > MAX_PDF_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {MAX_PDF_BYTES} bytes",
        )

    storage = get_storage_service()
    object_id = uuid4()
    pdf_key = storage.upload_pdf(
        tenant_id=tenant_id,
        object_id=object_id,
        body=body,
        original_filename=file.filename,
    )

    doc = Document(
        tenant_id=tenant_id,
        source=DocumentSource.UPLOAD,
        status=DocumentStatus.PENDING,
        pdf_key=pdf_key,
        original_filename=file.filename,
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)

    # Encolar extracción IA (no romper si broker no está disponible).
    try:
        from app.workers.tasks import extract_document  # local import: evita circulares

        extract_document.delay(str(doc.id))
        log.info("document.uploaded.enqueued", document_id=str(doc.id))
    except Exception as e:
        log.warning(
            "document.uploaded.enqueue_failed",
            document_id=str(doc.id),
            error=str(e),
            hint="¿Redis arrancado? El Document queda en pending — re-procesar manualmente.",
        )

    return doc


# =============================================================================
# Edición / aprobación
# =============================================================================


class ExtractedJsonPatch(BaseModel):
    """Body del PATCH /documents/{id}/extracted — sustituye `extracted_json`."""

    extracted_json: dict[str, Any] = Field(
        ...,
        description="JSON corregido por el revisor humano. Sustituye el extraído por la IA.",
    )


class StatusPatch(BaseModel):
    """Body del PATCH /documents/{id}/status — cambio de estado por el revisor."""

    status: DocumentStatus
    reason: str | None = Field(default=None, max_length=500)


_EDITABLE_STATUSES = {
    DocumentStatus.EXTRACTED,
    DocumentStatus.APPROVED,
    DocumentStatus.REJECTED,
}

_APPROVAL_TRANSITIONS: dict[DocumentStatus, set[DocumentStatus]] = {
    DocumentStatus.EXTRACTED: {DocumentStatus.APPROVED, DocumentStatus.REJECTED},
    DocumentStatus.APPROVED: {DocumentStatus.EXTRACTED, DocumentStatus.REJECTED},
    DocumentStatus.REJECTED: {DocumentStatus.EXTRACTED, DocumentStatus.APPROVED},
}


@router.patch("/{document_id}/extracted", response_model=DocumentRead)
def patch_extracted(
    document_id: UUID,
    payload: ExtractedJsonPatch,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> Document:
    """Guarda correcciones humanas sobre `extracted_json`.

    Solo permitido cuando el documento ya está extraído (no en pending/processing).
    """
    doc = session.get(Document, document_id)
    if doc is None or doc.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if doc.status not in _EDITABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot edit document in status '{doc.status}' — wait until extraction finishes",
        )

    doc.extracted_json = payload.extracted_json
    doc.updated_at = datetime.now(UTC)
    session.add(doc)
    session.commit()
    session.refresh(doc)
    log.info("document.extracted.patched", document_id=str(document_id))
    return doc


# =============================================================================
# Cambio manual de tipo + reclasificación bulk
# =============================================================================


class TypePatch(BaseModel):
    document_type: DocumentType


@router.patch("/{document_id}/type", response_model=DocumentRead)
def patch_document_type(
    document_id: UUID,
    payload: TypePatch,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> Document:
    """Cambio manual del tipo de documento (pedido / oferta / desconocido).

    Si pasa a `pedido` y no tiene oferta vinculada, intenta auto-link.
    Si pasa a `oferta` y tenía link como pedido, lo desvincula (ya no es pedido).
    """
    doc = session.get(Document, document_id)
    if doc is None or doc.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Document not found")

    old_type = doc.document_type
    doc.document_type = payload.document_type
    doc.updated_at = datetime.now(UTC)
    session.add(doc)
    session.commit()
    session.refresh(doc)

    # Si dejó de ser pedido → quitar el link como pedido si existía
    if old_type == DocumentType.PEDIDO and payload.document_type != DocumentType.PEDIDO:
        existing = session.exec(
            select(DocumentLink).where(DocumentLink.order_document_id == document_id)
        ).first()
        if existing is not None:
            session.delete(existing)
            session.commit()

    # Si pasó a pedido → intentar auto-link
    if payload.document_type == DocumentType.PEDIDO and old_type != DocumentType.PEDIDO:
        existing = session.exec(
            select(DocumentLink).where(DocumentLink.order_document_id == document_id)
        ).first()
        if existing is None:
            match = find_matching_offer(
                session,
                tenant_id=tenant_id,
                order_extracted=doc.extracted_json or {},
                order_doc_id=document_id,
            )
            if match is not None:
                offer, strategy, score = match
                comparison = compare_order_vs_offer(
                    doc.extracted_json or {}, offer.extracted_json or {}
                )
                session.add(
                    DocumentLink(
                        tenant_id=tenant_id,
                        order_document_id=document_id,
                        offer_document_id=offer.id,
                        match_strategy=strategy,
                        match_score=score,
                        comparison_result=comparison,
                    )
                )
                session.commit()

    log.info(
        "document.type.patched",
        document_id=str(document_id),
        old_type=old_type.value,
        new_type=payload.document_type.value,
    )
    return doc


# =============================================================================
# Reclasificar bulk (heurística filename + Claude)
# =============================================================================


class ReclassifyResult(BaseModel):
    inspected: int
    changed: int
    by_type: dict[str, int]
    relinked: int  # cuántos pedidos consiguieron vincular oferta tras reclassify


@router.post("/reclassify", response_model=ReclassifyResult)
def reclassify_all(
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
    only_unknown: Annotated[bool, Query()] = True,
) -> ReclassifyResult:
    """Re-aplica `classify_document` a los documentos del tenant.

    - `only_unknown=true` (default): solo recalcula los que están en `desconocido`.
    - `only_unknown=false`: recalcula TODOS (cuidado, puede recategorizar pedidos manuales).

    Tras re-clasificar, intenta auto-vincular pedidos nuevos a ofertas existentes.
    """
    query = select(Document).where(Document.tenant_id == tenant_id)
    if only_unknown:
        query = query.where(Document.document_type == DocumentType.DESCONOCIDO)

    docs = list(session.exec(query).all())
    by_type: dict[str, int] = {"pedido": 0, "oferta": 0, "desconocido": 0}
    changed = 0
    new_pedidos: list[Document] = []

    for doc in docs:
        new_type = classify_document(
            filename=doc.original_filename,
            extracted_json=doc.extracted_json,
        )
        if new_type != doc.document_type:
            doc.document_type = new_type
            doc.updated_at = datetime.now(UTC)
            # Si pasa a OFERTA, auto-aprobar (catálogo pasivo, sin validación)
            if new_type == DocumentType.OFERTA and doc.status == DocumentStatus.EXTRACTED:
                doc.status = DocumentStatus.APPROVED
            session.add(doc)
            changed += 1
            if new_type == DocumentType.PEDIDO:
                new_pedidos.append(doc)
        by_type[new_type.value] += 1

    session.commit()

    # Re-intentar matching para pedidos que cambiaron a "pedido" sin link previo
    relinked = 0
    for order in new_pedidos:
        existing_link = session.exec(
            select(DocumentLink).where(DocumentLink.order_document_id == order.id)
        ).first()
        if existing_link is not None:
            continue
        match = find_matching_offer(
            session,
            tenant_id=tenant_id,
            order_extracted=order.extracted_json or {},
            order_doc_id=order.id,
        )
        if match is None:
            continue
        offer, strategy, score = match
        comparison = compare_order_vs_offer(order.extracted_json or {}, offer.extracted_json or {})
        link = DocumentLink(
            tenant_id=tenant_id,
            order_document_id=order.id,
            offer_document_id=offer.id,
            match_strategy=strategy,
            match_score=score,
            comparison_result=comparison,
        )
        session.add(link)
        relinked += 1
    session.commit()

    log.info(
        "documents.reclassified",
        tenant_id=str(tenant_id),
        inspected=len(docs),
        changed=changed,
        relinked=relinked,
        by_type=by_type,
    )
    return ReclassifyResult(
        inspected=len(docs), changed=changed, by_type=by_type, relinked=relinked
    )


# =============================================================================
# Bulk re-validación contra catálogo + reglas workflow
# =============================================================================


class RevalidateResult(BaseModel):
    inspected: int  # docs revisados
    updated: int  # docs cuyo extracted_json cambió
    blocking_now: int  # docs que AHORA tienen bloqueos (validation o workflow)
    blocking_before: int  # docs que YA tenían bloqueos antes
    new_blocks: int  # docs que pasaron de OK a bloqueado
    cleared_blocks: int  # docs que pasaron de bloqueado a OK


@router.post("/revalidate", response_model=RevalidateResult)
def revalidate_all(
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
    only_extracted: Annotated[bool, Query()] = False,
) -> RevalidateResult:
    """Re-aplica validación catálogo + reglas workflow a docs ya extraídos.

    Útil tras subir un catálogo nuevo (precios mínimos cambiaron) o tras editar
    reglas workflow. Recalcula `extracted_json.validation` y `extracted_json.workflow`
    + `has_blocking_issues` sin re-llamar a OCR/Claude (rápido y gratis).

    - `only_extracted=true`: solo procesa docs en estado `extracted` (recién extraídos
      pendientes de aprobación).
    - `only_extracted=false` (default): procesa también `approved` y `rejected` para
      reflejar la "verdad actual" en históricos (no cambia su status).
    """
    valid_states = (
        [DocumentStatus.EXTRACTED]
        if only_extracted
        else [DocumentStatus.EXTRACTED, DocumentStatus.APPROVED, DocumentStatus.REJECTED]
    )
    docs = list(
        session.exec(
            select(Document).where(
                Document.tenant_id == tenant_id,
                Document.status.in_(valid_states),  # type: ignore[attr-defined]
                Document.extracted_json.is_not(None),  # type: ignore[union-attr]
            )
        ).all()
    )
    catalog = list(
        session.exec(select(CatalogItem).where(CatalogItem.tenant_id == tenant_id)).all()
    )
    rules = list(
        session.exec(select(WorkflowRule).where(WorkflowRule.tenant_id == tenant_id)).all()
    )

    updated = blocking_now = blocking_before = new_blocks = cleared_blocks = 0

    for doc in docs:
        original = doc.extracted_json or {}
        was_blocked = bool(doc.has_blocking_issues)
        if was_blocked:
            blocking_before += 1

        new_data = dict(original)
        new_data["validation"] = validate_against_catalog(new_data, catalog)
        # `document_type` puede venir como Enum (Postgres) o str (SQLite tests)
        doc_type_str = (
            doc.document_type.value
            if hasattr(doc.document_type, "value")
            else str(doc.document_type)
        )
        workflow_result = evaluate_rules(rules, new_data, document_type=doc_type_str)
        # `_matched_uuid_ids` es interno (lista de IDs para incrementar hits) — no
        # lo persistimos en extracted_json. Lo eliminamos antes de guardar.
        workflow_result.pop("_matched_uuid_ids", None)
        new_data["workflow"] = workflow_result

        is_blocked = bool(workflow_result.get("blocked")) or (
            ((new_data.get("validation") or {}).get("summary") or {}).get("blocking", 0) > 0
        )
        if is_blocked:
            blocking_now += 1

        if new_data != original or doc.has_blocking_issues != is_blocked:
            doc.extracted_json = new_data
            doc.has_blocking_issues = is_blocked
            doc.updated_at = datetime.now(UTC)
            session.add(doc)
            updated += 1
            if is_blocked and not was_blocked:
                new_blocks += 1
            elif was_blocked and not is_blocked:
                cleared_blocks += 1

    session.commit()
    log.info(
        "documents.revalidated",
        tenant_id=str(tenant_id),
        inspected=len(docs),
        updated=updated,
        blocking_now=blocking_now,
        new_blocks=new_blocks,
        cleared_blocks=cleared_blocks,
    )
    return RevalidateResult(
        inspected=len(docs),
        updated=updated,
        blocking_now=blocking_now,
        blocking_before=blocking_before,
        new_blocks=new_blocks,
        cleared_blocks=cleared_blocks,
    )


# =============================================================================
# Link pedido ↔ oferta
# =============================================================================


class LinkOfferPayload(BaseModel):
    """Vincular manualmente un pedido a una oferta."""

    offer_document_id: UUID


def _comparison_has_discrepancies(comparison: dict[str, Any] | None) -> bool:
    if not comparison:
        return False
    summary = comparison.get("summary") or {}
    return any(
        summary.get(k, 0) > 0
        for k in (
            "price_discrepancies",
            "qty_discrepancies",
            "added_in_order",
            "removed_from_offer",
        )
    )


@router.get("/{document_id}/linked-orders", response_model=list[DocumentLinkRead])
def get_linked_orders(
    document_id: UUID,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> list[DocumentLink]:
    """Lista los pedidos vinculados a una oferta (para navegar oferta→pedido)."""
    doc = session.get(Document, document_id)
    if doc is None or doc.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Document not found")
    return list(
        session.exec(
            select(DocumentLink)
            .where(DocumentLink.tenant_id == tenant_id)
            .where(DocumentLink.offer_document_id == document_id)
        ).all()
    )


@router.get("/{document_id}/link", response_model=DocumentLinkRead | None)
def get_document_link(
    document_id: UUID,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> DocumentLink | None:
    """Devuelve el DocumentLink (pedido↔oferta) si existe."""
    doc = session.get(Document, document_id)
    if doc is None or doc.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Document not found")
    return session.exec(
        select(DocumentLink).where(DocumentLink.order_document_id == document_id)
    ).first()


@router.post("/{document_id}/link", response_model=DocumentLinkRead, status_code=201)
def link_offer_manually(
    document_id: UUID,
    payload: LinkOfferPayload,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> DocumentLink:
    """Vincula un pedido a una oferta manualmente (sustituye link previo si lo hay)."""
    order = session.get(Document, document_id)
    if order is None or order.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Order document not found")
    if order.document_type != DocumentType.PEDIDO:
        raise HTTPException(
            status_code=400, detail=f"Document is type '{order.document_type}', not pedido"
        )
    offer = session.get(Document, payload.offer_document_id)
    if offer is None or offer.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Offer document not found")
    if offer.document_type != DocumentType.OFERTA:
        raise HTTPException(
            status_code=400, detail=f"Target document is type '{offer.document_type}', not oferta"
        )

    # Borrar link previo si existe
    existing = session.exec(
        select(DocumentLink).where(DocumentLink.order_document_id == document_id)
    ).first()
    if existing is not None:
        session.delete(existing)
        session.flush()

    comparison = compare_order_vs_offer(order.extracted_json or {}, offer.extracted_json or {})
    link = DocumentLink(
        tenant_id=tenant_id,
        order_document_id=document_id,
        offer_document_id=payload.offer_document_id,
        match_strategy=MatchStrategy.MANUAL,
        match_score=1.0,
        comparison_result=comparison,
    )
    session.add(link)
    order.has_discrepancies = _comparison_has_discrepancies(comparison)
    session.add(order)
    session.commit()
    session.refresh(link)

    # Tras link manual, intentar también la expansión 1-línea-resumen
    from app.workers.tasks import _maybe_expand_lines_from_offer

    _maybe_expand_lines_from_offer(document_id, payload.offer_document_id, session=session)

    return link


@router.delete("/{document_id}/link", status_code=204)
def unlink_offer(
    document_id: UUID,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    doc = session.get(Document, document_id)
    if doc is None or doc.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Document not found")
    existing = session.exec(
        select(DocumentLink).where(DocumentLink.order_document_id == document_id)
    ).first()
    if existing is None:
        return
    session.delete(existing)
    doc.has_discrepancies = False
    session.add(doc)
    session.commit()


@router.post("/{document_id}/auto-link", response_model=DocumentLinkRead | None)
def auto_link_offer(
    document_id: UUID,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> DocumentLink | None:
    """Re-intenta el matching automático (útil cuando han llegado nuevas ofertas)."""
    order = session.get(Document, document_id)
    if order is None or order.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Document not found")
    if order.document_type != DocumentType.PEDIDO:
        raise HTTPException(
            status_code=400, detail=f"Document is type '{order.document_type}', not pedido"
        )

    match = find_matching_offer(
        session,
        tenant_id=tenant_id,
        order_extracted=order.extracted_json or {},
        order_doc_id=document_id,
    )
    if match is None:
        return None
    offer, strategy, score = match
    comparison = compare_order_vs_offer(order.extracted_json or {}, offer.extracted_json or {})

    existing = session.exec(
        select(DocumentLink).where(DocumentLink.order_document_id == document_id)
    ).first()
    if existing is not None:
        session.delete(existing)
        session.flush()
    link = DocumentLink(
        tenant_id=tenant_id,
        order_document_id=document_id,
        offer_document_id=offer.id,
        match_strategy=strategy,
        match_score=score,
        comparison_result=comparison,
    )
    session.add(link)
    order.has_discrepancies = _comparison_has_discrepancies(comparison)
    session.add(order)
    session.commit()
    session.refresh(link)

    # Tras vincular: si el pedido es 1-línea-resumen y los totales con la oferta
    # cuadran, expandir las líneas con las refs reales de la oferta. Hace
    # innecesario re-procesar el pedido entero (no llama a OCR/Claude).
    from app.workers.tasks import _maybe_expand_lines_from_offer

    _maybe_expand_lines_from_offer(document_id, offer.id, session=session)

    return link


@router.patch("/{document_id}/status", response_model=DocumentRead)
def patch_status(
    document_id: UUID,
    payload: StatusPatch,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> Document:
    """Cambia el estado del documento (aprobar/rechazar/reabrir).

    Bloqueado por reglas workflow: si `extracted_json.workflow.blocked == true`
    y se intenta aprobar, devuelve 409 con la lista de reglas bloqueantes.
    """
    doc = session.get(Document, document_id)
    if doc is None or doc.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    allowed = _APPROVAL_TRANSITIONS.get(doc.status, set())
    if payload.status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Invalid transition: {doc.status} -> {payload.status}. Allowed: {sorted(allowed)}",
        )

    # Bloqueo workflow al aprobar
    if payload.status == DocumentStatus.APPROVED:
        wf = (doc.extracted_json or {}).get("workflow") or {}
        if wf.get("blocked"):
            blockers = wf.get("blocking_rules") or []
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "Aprobación bloqueada por reglas de workflow.",
                    "blocking_rules": blockers,
                },
            )

    doc.status = payload.status
    if payload.reason:
        doc.extraction_error = f"[{payload.status}] {payload.reason}"
    doc.updated_at = datetime.now(UTC)
    session.add(doc)
    session.commit()
    session.refresh(doc)
    log.info(
        "document.status.patched",
        document_id=str(document_id),
        new_status=payload.status,
    )
    return doc


# =============================================================================
# Push a ERP (capa erp/)
# =============================================================================


@router.post("/{document_id}/push-to-erp", response_model=DocumentRead)
def push_document_to_erp(
    document_id: UUID,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> Document:
    """Empuja el documento al ERP configurado (hoy: ERPNext).

    Requiere `status=approved` y `document_type=pedido`. El push se considera
    éxito si el ERP devuelve un ID; el documento queda en estado `Draft` en el
    ERP — el usuario lo confirma allí manualmente.

    Es **idempotente desde la perspectiva del usuario**: re-pulsar crea un
    Sales Order nuevo cada vez (no actualiza el anterior). Esto es deliberado
    — re-pushing tras corregir datos es válido. Si quieres deduplicar, primero
    cancela el SO viejo en el ERP.
    """
    doc = session.get(Document, document_id)
    if doc is None or doc.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if doc.document_type != DocumentType.PEDIDO:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Solo se pueden empujar pedidos al ERP. Tipo actual: {doc.document_type}. "
                "Si es un pedido mal clasificado, cambia el tipo desde el detalle del documento."
            ),
        )
    if doc.status != DocumentStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"El pedido debe estar en estado 'approved' para empujarlo al ERP. "
                f"Estado actual: {doc.status}."
            ),
        )
    if not doc.extracted_json:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Documento sin datos extraídos — no hay nada que empujar.",
        )

    adapter = get_erp_adapter()
    if adapter is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "No hay ERP configurado en el servidor. Configura las variables "
                "ERPNEXT_BASE_URL, ERPNEXT_API_KEY, ERPNEXT_API_SECRET y "
                "ERPNEXT_DEFAULT_COMPANY en el .env."
            ),
        )

    # 1. Mapping a modelo canónico
    try:
        canonical = extracted_to_sales_order(document_id=doc.id, extracted=doc.extracted_json)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Datos del pedido insuficientes para empujar al ERP: {e}",
        ) from e

    # 2. Push y manejo de errores tipados
    try:
        result = adapter.push_sales_order(canonical)
    except AuthError as e:
        # Error de credenciales: NO marcamos doc.erp_push_error porque es global
        log.error("erp.push.auth_error", document_id=str(document_id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Credenciales del ERP rechazadas. Revisa ERPNEXT_API_KEY/SECRET.",
        ) from e
    except CustomerNotRegisteredError as e:
        # Estado de negocio NORMAL: el cliente no está dado de alta en el ERP.
        # Guardamos el error para que la UI pueda mostrar acción específica
        # ("Dar de alta cliente"), no un genérico "intenta de nuevo".
        doc.erp_push_error = f"customer_not_registered: {e.customer_name}"
        doc.updated_at = datetime.now(UTC)
        session.add(doc)
        session.commit()
        log.info(
            "erp.push.customer_not_registered",
            document_id=str(document_id),
            customer_name=e.customer_name,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "customer_not_registered",
                "message": (
                    f"El cliente '{e.customer_name}' no está dado de alta en tu ERP. "
                    "Sube primero la ficha de alta del cliente para que Order Flow lo "
                    "registre con todos sus datos (dirección, contacto, condiciones de pago)."
                ),
                "customer_name": e.customer_name,
                "lookup_hints": e.lookup_hints,
            },
        ) from e
    except (ERPNotFoundError, ERPValidationError) as e:
        # Error semántico del ERP — guardamos para diagnóstico
        doc.erp_push_error = f"{type(e).__name__}: {e}"
        doc.updated_at = datetime.now(UTC)
        session.add(doc)
        session.commit()
        log.warning(
            "erp.push.validation_error",
            document_id=str(document_id),
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"El ERP rechazó el documento: {e}",
        ) from e
    except TransientError as e:
        log.warning("erp.push.transient_error", document_id=str(document_id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"ERP temporalmente no disponible: {e}. Reintenta en unos segundos.",
        ) from e
    except ERPAdapterError as e:
        log.exception("erp.push.adapter_error", document_id=str(document_id))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error al hablar con el ERP: {e}",
        ) from e

    # 3. Persistir resultado
    doc.erp_adapter = adapter.name
    doc.erp_id = result.erp_id
    doc.erp_url = result.erp_url
    doc.erp_pushed_at = datetime.now(UTC)
    doc.erp_push_error = None
    doc.updated_at = doc.erp_pushed_at
    session.add(doc)
    session.commit()
    session.refresh(doc)

    log.info(
        "erp.push.ok",
        document_id=str(document_id),
        adapter=adapter.name,
        erp_id=result.erp_id,
    )
    return doc
