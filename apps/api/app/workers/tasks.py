"""Tasks Celery — orquestación OCR + extracción IA.

Pipeline para extract_document:
    1. Cargar Document (status pending|failed → processing)
    2. Descargar PDF de storage
    3. OCR (Mistral) → markdown + ocr_result raw
    4. Extracción (Claude) → JSON estructurado + source_texts
    5. Guardar ocr_result + extracted_json + status=extracted

Modo dev sin Redis: poner CELERY_TASK_ALWAYS_EAGER=true en .env.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlmodel import Session, select

from app.core.db import engine
from app.core.logging import get_logger
from app.models.catalog_item import CatalogItem
from app.models.concept import Concept
from app.models.document import Document, DocumentSource, DocumentStatus, DocumentType
from app.models.document_link import DocumentLink
from app.models.email_integration import EmailIntegration, IntegrationStatus
from app.models.tenant_field import TenantField
from app.models.workflow_rule import WorkflowRule
from app.services import msgraph
from app.services.classification import classify_document
from app.services.concepts import apply_concepts, increment_hits
from app.services.extraction import ExtractionError, ExtractionService
from app.services.matching import compare_order_vs_offer, find_matching_offer
from app.services.ocr import OCRError, get_ocr_provider
from app.services.rules_engine import evaluate_rules
from app.services.storage import get_storage_service
from app.services.validation import validate_against_catalog
from app.workers.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(
    name="app.workers.tasks.extract_document",
    bind=True,
    autoretry_for=(ExtractionError, OCRError),
    retry_kwargs={"max_retries": 2, "countdown": 30},
    acks_late=True,
)
def extract_document(self, document_id: str) -> dict:
    doc_uuid = UUID(document_id)
    log.info("task.extract_document.start", document_id=document_id, retry=self.request.retries)

    with Session(engine) as session:
        doc = session.get(Document, doc_uuid)
        if doc is None:
            log.warning("task.extract_document.not_found", document_id=document_id)
            return {"status": "not_found", "document_id": document_id}

        if doc.status not in (DocumentStatus.PENDING, DocumentStatus.FAILED):
            log.info(
                "task.extract_document.skip",
                document_id=document_id,
                current_status=doc.status,
            )
            return {"status": "skipped", "document_id": document_id}

        doc.status = DocumentStatus.PROCESSING
        doc.extraction_error = None
        doc.updated_at = datetime.now(UTC)
        session.add(doc)
        session.commit()
        session.refresh(doc)

        pdf_key = doc.pdf_key

    try:
        # 1. Descargar PDF
        storage = get_storage_service()
        pdf_bytes = storage.download_pdf(pdf_key)

        # 2. OCR
        ocr_provider = get_ocr_provider()
        ocr_result = ocr_provider.extract(pdf_bytes)
        markdown = ocr_result.full_markdown

        # Cargar concepts del tenant + globales para extraer field_aliases
        # y los TenantField (campos custom dinámicos) para extender el prompt.
        from sqlalchemy import or_

        with Session(engine) as session_pre:
            doc_pre = session_pre.get(Document, doc_uuid)
            tenant_id_for_pre = doc_pre.tenant_id if doc_pre else None
            field_aliases: dict[str, list[str]] = {}
            custom_field_specs: list[tuple[str, str, str | None]] = []
            if tenant_id_for_pre is not None:
                concepts_pre = session_pre.exec(
                    select(Concept).where(
                        or_(Concept.tenant_id == tenant_id_for_pre, Concept.tenant_id.is_(None))
                    )
                ).all()
                for c in concepts_pre:
                    if c.field_path and c.aliases:
                        field_aliases.setdefault(c.field_path, []).extend(c.aliases)
                tenant_fields_pre = session_pre.exec(
                    select(TenantField).where(TenantField.tenant_id == tenant_id_for_pre)
                ).all()
                custom_field_specs = [
                    (tf.key, tf.label, tf.description) for tf in tenant_fields_pre
                ]

        # 3. Extracción IA con el markdown del OCR + pistas de campos del tenant
        service = ExtractionService()
        result = service.extract(
            markdown,
            tenant_context=None,
            field_aliases=field_aliases,
            custom_field_specs=custom_field_specs,
        )

    except (OCRError, ExtractionError) as e:
        with Session(engine) as session:
            doc = session.get(Document, doc_uuid)
            if doc is not None:
                doc.status = DocumentStatus.FAILED
                doc.extraction_error = str(e)
                doc.processed_at = datetime.now(UTC)
                doc.updated_at = doc.processed_at
                session.add(doc)
                session.commit()
        log.error("task.extract_document.failed", document_id=document_id, error=str(e))
        raise
    except Exception as e:
        with Session(engine) as session:
            doc = session.get(Document, doc_uuid)
            if doc is not None:
                doc.status = DocumentStatus.FAILED
                doc.extraction_error = f"unexpected: {e}"
                doc.processed_at = datetime.now(UTC)
                doc.updated_at = doc.processed_at
                session.add(doc)
                session.commit()
        log.exception("task.extract_document.unexpected", document_id=document_id)
        raise

    # 4. Aplicar Concepts (per-tenant + globales) + validar catálogo + reglas workflow
    from sqlalchemy import or_

    with Session(engine) as session:
        doc = session.get(Document, doc_uuid)
        if doc is None:
            return {"status": "lost", "document_id": document_id}
        tenant_id = doc.tenant_id
        concepts = list(
            session.exec(
                select(Concept).where(
                    or_(Concept.tenant_id == tenant_id, Concept.tenant_id.is_(None))
                )
            ).all()
        )
        catalog = list(
            session.exec(select(CatalogItem).where(CatalogItem.tenant_id == tenant_id)).all()
        )
        rules = list(
            session.exec(select(WorkflowRule).where(WorkflowRule.tenant_id == tenant_id)).all()
        )

    # Aplica solo concepts SIN field_path (los con field_path se inyectaron al prompt)
    raw_extracted = result.model_dump(mode="json")
    free_concepts = [c for c in concepts if not c.field_path]
    mapped_extracted, hit_ids = apply_concepts(raw_extracted, free_concepts)
    mapped_extracted["validation"] = validate_against_catalog(mapped_extracted, catalog)

    # 5. Clasificar tipo (filename heurística + JSON Claude)
    with Session(engine) as session:
        doc = session.get(Document, doc_uuid)
        if doc is None:
            return {"status": "lost", "document_id": document_id}
        original_filename = doc.original_filename
    detected_type = classify_document(
        filename=original_filename,
        extracted_json=mapped_extracted,
    )

    # 5b. Evaluar reglas workflow (después de saber el tipo)
    workflow_result = evaluate_rules(rules, mapped_extracted, document_type=detected_type.value)
    rule_hit_ids = workflow_result.pop("_matched_uuid_ids", [])
    mapped_extracted["workflow"] = workflow_result

    # Flag pre-calculado para la bandeja
    has_blocking = bool(workflow_result.get("blocked")) or (
        ((mapped_extracted.get("validation") or {}).get("summary") or {}).get("blocking", 0) > 0
    )

    # 6. Persistir ocr_result + extracted_json + tipo + incrementar hits
    with Session(engine) as session:
        doc = session.get(Document, doc_uuid)
        if doc is None:
            return {"status": "lost", "document_id": document_id}
        doc.ocr_result = ocr_result.model_dump(mode="json")
        doc.raw_text = markdown
        doc.extracted_json = mapped_extracted
        doc.document_type = detected_type
        doc.status = DocumentStatus.EXTRACTED
        doc.has_blocking_issues = has_blocking
        doc.processed_at = datetime.now(UTC)
        doc.updated_at = doc.processed_at
        session.add(doc)
        session.commit()
        increment_hits(session, hit_ids)
        # Incrementar hits de las reglas que matchearon
        for rid in rule_hit_ids:
            r = session.get(WorkflowRule, rid)
            if r is not None:
                r.hits += 1
                session.add(r)
        if rule_hit_ids:
            session.commit()

    # 7. Si es PEDIDO, intentar vincular con una oferta del tenant
    matched: dict[str, Any] | None = None
    expanded: dict[str, Any] | None = None
    if detected_type == DocumentType.PEDIDO:
        matched = _try_link_order_to_offer(doc_uuid, mapped_extracted, tenant_id)
        # 7b. Si la oferta vinculada existe Y el pedido tiene 1 línea-resumen
        # cuyo total cuadra con la oferta, expandir las líneas del pedido con
        # las refs reales de la oferta para poder pushearlas a Sage.
        if matched is not None:
            expanded = _maybe_expand_lines_from_offer(doc_uuid, UUID(matched["offer_id"]))

    log.info(
        "task.extract_document.ok",
        document_id=document_id,
        ocr_pages=len(ocr_result.pages),
        lineas=len(result.lineas),
        mappings_applied=len(hit_ids),
        document_type=detected_type.value,
        matched_offer=matched["offer_id"] if matched else None,
        lines_expanded=expanded["expanded_to"] if expanded else None,
    )
    return {
        "status": "extracted",
        "document_id": document_id,
        "lineas": len(result.lineas),
        "ocr_pages": len(ocr_result.pages),
        "mappings_applied": len(hit_ids),
        "document_type": detected_type.value,
        "matched_offer": matched,
        "lines_expanded_from_offer": expanded,
    }


def _try_link_order_to_offer(
    order_doc_id: UUID,
    order_extracted: dict[str, Any],
    tenant_id: UUID,
) -> dict[str, Any] | None:
    """Intenta vincular un pedido con una oferta. Persiste DocumentLink si match.

    Devuelve `{offer_id, strategy, score}` o None.
    """
    with Session(engine) as session:
        match = find_matching_offer(
            session,
            tenant_id=tenant_id,
            order_extracted=order_extracted,
            order_doc_id=order_doc_id,
        )
        if match is None:
            log.info("matching.no_offer_found", order_id=str(order_doc_id))
            return None

        offer, strategy, score = match
        comparison = compare_order_vs_offer(order_extracted, offer.extracted_json or {})

        link = DocumentLink(
            tenant_id=tenant_id,
            order_document_id=order_doc_id,
            offer_document_id=offer.id,
            match_strategy=strategy,
            match_score=score,
            comparison_result=comparison,
        )
        session.add(link)
        # Marcar el pedido como "tiene discrepancias" si las hay
        summary = comparison.get("summary", {})
        if any(
            summary.get(k, 0) > 0
            for k in (
                "price_discrepancies",
                "qty_discrepancies",
                "added_in_order",
                "removed_from_offer",
            )
        ):
            order = session.get(Document, order_doc_id)
            if order is not None:
                order.has_discrepancies = True
                session.add(order)
        session.commit()
        log.info(
            "matching.linked",
            order_id=str(order_doc_id),
            offer_id=str(offer.id),
            strategy=strategy.value,
            score=round(score, 3),
            price_disc=comparison["summary"]["price_discrepancies"],
            qty_disc=comparison["summary"]["qty_discrepancies"],
        )
        return {
            "offer_id": str(offer.id),
            "strategy": strategy.value,
            "score": score,
        }


# Tolerancia entre el total del pedido (1 línea-resumen) y la suma de
# importes de la oferta. Si la diferencia relativa es menor → expandimos.
EXPAND_TOTAL_TOLERANCE = 0.01  # 1%


def _line_amount(line: dict[str, Any]) -> float:
    """Importe efectivo de una línea: importe_linea o cantidad×precio."""
    importe = line.get("importe_linea")
    if importe is not None:
        try:
            return float(importe)
        except (TypeError, ValueError):
            return 0.0
    cantidad = line.get("cantidad") or 0
    precio = line.get("precio_unitario") or 0
    try:
        return float(cantidad) * float(precio)
    except (TypeError, ValueError):
        return 0.0


def _maybe_expand_lines_from_offer(
    order_doc_id: UUID,
    offer_doc_id: UUID,
    *,
    session: Session | None = None,
) -> dict[str, Any] | None:
    """Si el pedido tiene 1 línea-resumen y su total cuadra con la oferta,
    reemplaza las líneas del pedido por las de la oferta.

    Caso típico: el cliente envía un pedido escrito a mano que dice solo
    "Según oferta TL260417-113, total 1234,00€" en una sola línea. Sin esto
    no podemos pushear refs reales a Sage 200.

    `session` opcional para tests; en producción abre uno nuevo.
    Devuelve `{expanded_to, order_total, offer_total, offer_id}` o None.
    """
    if session is None:
        with Session(engine) as new_session:
            return _maybe_expand_lines_from_offer(order_doc_id, offer_doc_id, session=new_session)

    order = session.get(Document, order_doc_id)
    offer = session.get(Document, offer_doc_id)
    if order is None or offer is None:
        return None

    order_data = dict(order.extracted_json or {})
    offer_data = offer.extracted_json or {}

    order_lines: list[dict[str, Any]] = list(order_data.get("lineas") or [])
    offer_lines: list[dict[str, Any]] = list(offer_data.get("lineas") or [])

    # Solo aplica si el pedido tiene exactamente 1 línea
    if len(order_lines) != 1:
        return None
    # Y la oferta tiene 2+ líneas (sino no expandimos nada útil)
    if len(offer_lines) < 2:
        return None

    # Total del pedido — preferimos subtotal_ht (sin IVA, sin transporte)
    order_total_raw = (order_data.get("totales") or {}).get("subtotal_ht")
    if order_total_raw is None:
        # Fallback: sumar la única línea (que típicamente lleva el total)
        order_total_raw = _line_amount(order_lines[0])
    try:
        order_total = float(order_total_raw)
    except (TypeError, ValueError):
        return None
    if order_total <= 0:
        return None

    # Total de la oferta = suma de importes de líneas (no usar totales.subtotal_ht
    # de la oferta porque puede incluir transporte; queremos solo el material).
    offer_total = sum(_line_amount(line) for line in offer_lines)
    if offer_total <= 0:
        return None

    # Tolerancia 1%
    rel_diff = abs(order_total - offer_total) / max(order_total, offer_total)
    if rel_diff > EXPAND_TOTAL_TOLERANCE:
        log.info(
            "expand.totals_mismatch",
            order_id=str(order_doc_id),
            offer_id=str(offer_doc_id),
            order_total=order_total,
            offer_total=offer_total,
            rel_diff=round(rel_diff, 4),
        )
        return None

    # ¡Match! Expandimos las líneas del pedido con las de la oferta.
    original_line = order_lines[0]
    order_data["lineas"] = [dict(line) for line in offer_lines]
    order_data["lines_expanded_from_offer"] = {
        "offer_id": str(offer_doc_id),
        "original_line_count": 1,
        "expanded_to": len(offer_lines),
        "order_total": order_total,
        "offer_total": offer_total,
        "original_line_description": original_line.get("descripcion"),
    }

    # Re-validar contra catálogo (las nuevas líneas pueden disparar bloqueos)
    catalog = list(
        session.exec(select(CatalogItem).where(CatalogItem.tenant_id == order.tenant_id)).all()
    )
    order_data["validation"] = validate_against_catalog(order_data, catalog)
    # Recalcular flag has_blocking_issues con la nueva validation
    new_blocking = ((order_data.get("validation") or {}).get("summary") or {}).get(
        "blocking", 0
    ) > 0
    # Mantenemos workflow.blocked previo si existía
    wf_blocked = bool((order_data.get("workflow") or {}).get("blocked"))
    order.has_blocking_issues = new_blocking or wf_blocked

    order.extracted_json = order_data
    order.updated_at = datetime.now(UTC)
    session.add(order)
    session.commit()

    log.info(
        "expand.lines_from_offer.ok",
        order_id=str(order_doc_id),
        offer_id=str(offer_doc_id),
        expanded_to=len(offer_lines),
        order_total=order_total,
        offer_total=offer_total,
    )
    return {
        "offer_id": str(offer_doc_id),
        "expanded_to": len(offer_lines),
        "order_total": order_total,
        "offer_total": offer_total,
    }


# =============================================================================
# Outlook polling (Fase 4)
# =============================================================================


def _ensure_fresh_token(session: Session, integ: EmailIntegration) -> str:
    """Refresca access_token si está caducado. Devuelve un token válido."""
    if integ.access_token and integ.token_expires_at and integ.token_expires_at > datetime.now(UTC):
        return integ.access_token

    if not integ.refresh_token:
        raise msgraph.MSGraphError("No refresh token; reautoriza la integración")

    log.info("outlook.refresh_token", integration_id=str(integ.id))
    new_token = msgraph.refresh_tokens(integ.refresh_token)
    integ.access_token = new_token.access_token
    if new_token.refresh_token:
        integ.refresh_token = new_token.refresh_token
    integ.token_expires_at = msgraph.expires_at(new_token)
    integ.updated_at = datetime.now(UTC)
    session.add(integ)
    session.commit()
    session.refresh(integ)
    return integ.access_token


@celery_app.task(name="app.workers.tasks.poll_outlook_integration", bind=True)
def poll_outlook_integration(self, integration_id: str) -> dict:
    """Polls una integración Outlook: descarga attachments PDF nuevos como Documents.

    Flujo:
        1. Refresh token si hace falta
        2. Listar mensajes con adjuntos desde `last_polled_at`
        3. Por cada mensaje, por cada attachment PDF:
             - Subir a storage
             - Crear Document(source="email", source_email=From) en pending
             - Encolar extract_document
        4. Actualizar last_polled_at
    """
    integ_uuid = UUID(integration_id)
    log.info("outlook.poll.start", integration_id=integration_id)

    # Estados desde los que SE PUEDE intentar polling (manual o automático).
    # Solo skipeamos si el usuario la deshabilitó o aún no completó el OAuth.
    retryable = {
        IntegrationStatus.ACTIVE,
        IntegrationStatus.ERROR,
        IntegrationStatus.EXPIRED,
    }

    with Session(engine) as session:
        integ = session.get(EmailIntegration, integ_uuid)
        if integ is None:
            return {"status": "not_found"}
        if integ.status not in retryable:
            return {"status": "skipped", "reason": f"status={integ.status}"}

        try:
            access_token = _ensure_fresh_token(session, integ)
        except msgraph.MSGraphError as e:
            integ.status = IntegrationStatus.EXPIRED
            integ.last_error = str(e)
            session.add(integ)
            session.commit()
            log.warning("outlook.poll.token_failed", error=str(e))
            return {"status": "expired", "error": str(e)}

        since = integ.last_polled_at
        tenant_id = integ.tenant_id
        folder_id = integ.watched_folder_id

    try:
        messages = msgraph.list_messages_with_attachments(
            access_token, folder_id=folder_id, since=since, top=50
        )
    except msgraph.MSGraphError as e:
        with Session(engine) as session:
            integ = session.get(EmailIntegration, integ_uuid)
            if integ is not None:
                integ.last_error = str(e)
                integ.status = IntegrationStatus.ERROR
                session.add(integ)
                session.commit()
        log.error("outlook.poll.list_failed", error=str(e))
        return {"status": "error", "error": str(e)}

    # Query OK → limpiar error visible y restablecer status ya, sin esperar al
    # final del loop (que puede tardar minutos procesando attachments).
    with Session(engine) as session:
        integ = session.get(EmailIntegration, integ_uuid)
        if integ is not None:
            integ.last_error = None
            if integ.status in (IntegrationStatus.ERROR, IntegrationStatus.EXPIRED):
                integ.status = IntegrationStatus.ACTIVE
            integ.last_polled_at = datetime.now(UTC)
            integ.updated_at = datetime.now(UTC)
            session.add(integ)
            session.commit()

    new_documents = 0
    storage = get_storage_service()

    for msg in messages:
        msg_id = msg["id"]
        from_addr = (msg.get("from") or {}).get("emailAddress", {}).get("address")
        subject = msg.get("subject")
        # receivedDateTime viene en ISO 8601 con Z. Parseamos a datetime aware.
        received_str = msg.get("receivedDateTime")
        received_at: datetime | None = None
        if received_str:
            try:
                received_at = datetime.fromisoformat(received_str.replace("Z", "+00:00"))
            except ValueError:
                received_at = None

        try:
            attachments = msgraph.list_attachments(access_token, msg_id)
        except msgraph.MSGraphError as e:
            log.warning("outlook.poll.list_attachments_failed", msg_id=msg_id, error=str(e))
            continue

        for att in attachments:
            if att.get("@odata.type") != "#microsoft.graph.fileAttachment":
                continue
            content_type = att.get("contentType", "")
            name = att.get("name", "")
            if "pdf" not in content_type.lower() and not name.lower().endswith(".pdf"):
                continue

            try:
                pdf_bytes = msgraph.download_attachment(access_token, msg_id, att["id"])
            except msgraph.MSGraphError as e:
                log.warning(
                    "outlook.poll.download_failed",
                    msg_id=msg_id,
                    attachment=att.get("id"),
                    error=str(e),
                )
                continue

            object_id = uuid4()
            pdf_key = storage.upload_pdf(
                tenant_id=tenant_id,
                object_id=object_id,
                body=pdf_bytes,
                original_filename=name,
            )

            with Session(engine) as session:
                doc = Document(
                    tenant_id=tenant_id,
                    source=DocumentSource.EMAIL,
                    status=DocumentStatus.PENDING,
                    pdf_key=pdf_key,
                    original_filename=name,
                    source_email=from_addr,
                    email_received_at=received_at,
                )
                session.add(doc)
                session.commit()
                session.refresh(doc)
                doc_id = str(doc.id)
            new_documents += 1
            log.info(
                "outlook.poll.document_created",
                document_id=doc_id,
                from_addr=from_addr,
                subject=subject[:80] if subject else None,
            )
            extract_document.delay(doc_id)

    # 4. Update last_polled_at — recuperar status si estaba en error/expired
    with Session(engine) as session:
        integ = session.get(EmailIntegration, integ_uuid)
        if integ is not None:
            integ.last_polled_at = datetime.now(UTC)
            integ.last_error = None
            if integ.status in (IntegrationStatus.ERROR, IntegrationStatus.EXPIRED):
                integ.status = IntegrationStatus.ACTIVE
            integ.updated_at = datetime.now(UTC)
            session.add(integ)
            session.commit()

    log.info(
        "outlook.poll.ok",
        integration_id=integration_id,
        messages=len(messages),
        new_documents=new_documents,
    )
    return {"status": "ok", "messages": len(messages), "new_documents": new_documents}


@celery_app.task(name="app.workers.tasks.poll_all_outlook_integrations")
def poll_all_outlook_integrations() -> dict:
    """Tarea Celery beat: dispara poll_outlook_integration para cada integración activa."""
    with Session(engine) as session:
        active = list(
            session.exec(
                select(EmailIntegration).where(EmailIntegration.status == IntegrationStatus.ACTIVE)
            ).all()
        )
    for integ in active:
        poll_outlook_integration.delay(str(integ.id))
    return {"queued": len(active)}
