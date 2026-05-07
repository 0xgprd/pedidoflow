"""Matching pedido ↔ oferta + comparación de líneas (discrepancias).

Estrategias de matching (ver memory/project_quimilock_workflow.md):
1. EXACT_OFFER_NUMBER: el pedido declara un `numero_oferta` que coincide
   textualmente con el `numero_oferta` (o aparece en source_texts) de una oferta.
2. CLIENT_LINES_SIMILARITY: misma denominación de cliente (normalizada) +
   intersección de referencias entre líneas (Jaccard ≥ umbral).

La fecha NO se usa como criterio porque oferta y pedido pueden estar separados
semanas o meses.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any
from uuid import UUID

from sqlmodel import Session, select

from app.core.logging import get_logger
from app.models.catalog_item import normalize_reference
from app.models.document import Document, DocumentType
from app.models.document_link import DocumentLink, MatchStrategy

log = get_logger(__name__)

# Umbral mínimo de Jaccard de refs en común para aceptar match por similaridad
MIN_LINES_SIMILARITY = 0.3
# Umbral relativo de diferencia de precio para marcar discrepancia (5%)
PRICE_DIFF_TOLERANCE = 0.05
# Patrón de número de oferta Quimilock
OFFER_NUMBER_PATTERN = re.compile(r"TL\d{6}-\d+", re.IGNORECASE)


# =============================================================================
# Normalización
# =============================================================================


_SOCIETARY_SUFFIX_RE = re.compile(
    r"[\s,\.]+(s\.?a\.?s\.?u?|s\.?a\.?r\.?l|s\.?[al]|gmbh|ltd|inc|llc|bv|nv)\.?$",
    re.IGNORECASE,
)


def _normalize_client_name(name: str | None) -> str:
    """Lowercase + sin acentos + sin puntuación + sin sufijos societarios."""
    if not name:
        return ""
    s = name.strip().lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    # Quitar sufijos societarios al final (SAS, S.A.S., SL, GmbH, etc.)
    s = _SOCIETARY_SUFFIX_RE.sub("", s)
    return " ".join(s.split())


def _line_refs(extracted: dict[str, Any]) -> set[str]:
    """Conjunto de referencias normalizadas de las líneas (filtra None/vacías)."""
    refs: set[str] = set()
    for line in extracted.get("lineas", []) or []:
        if not isinstance(line, dict):
            continue
        ref = line.get("referencia")
        if ref:
            refs.add(normalize_reference(ref))
    return refs


def _extract_offer_numbers(extracted: dict[str, Any]) -> set[str]:
    """Extrae todos los números de oferta candidatos del JSON (campo + raw match)."""
    candidates: set[str] = set()
    pedido = extracted.get("pedido") or {}
    if isinstance(pedido, dict):
        n = pedido.get("numero_oferta")
        if n:
            candidates.add(n.strip().upper())
            for m in OFFER_NUMBER_PATTERN.findall(n):
                candidates.add(m.upper())
    # También buscar en source_texts y observaciones
    for value in (
        (pedido.get("observaciones") if isinstance(pedido, dict) else None),
        *(extracted.get("source_texts") or {}).values(),
    ):
        if isinstance(value, str):
            for m in OFFER_NUMBER_PATTERN.findall(value):
                candidates.add(m.upper())
    return candidates


# =============================================================================
# Matching
# =============================================================================


def find_matching_offer(
    session: Session,
    *,
    tenant_id: UUID,
    order_extracted: dict[str, Any],
    order_doc_id: UUID,
) -> tuple[Document, MatchStrategy, float] | None:
    """Busca una oferta del mismo tenant que vincular al pedido.

    Devuelve `(offer_document, strategy, score)` o `None` si no encuentra match.
    Solo considera ofertas del tenant que NO estén ya vinculadas a otro pedido.
    """
    # 1. EXACT_OFFER_NUMBER
    offer_numbers = _extract_offer_numbers(order_extracted)
    if offer_numbers:
        candidates = _candidate_offers(session, tenant_id, exclude_doc_id=order_doc_id)
        for offer in candidates:
            offer_extracted = offer.extracted_json or {}
            offer_nums = _extract_offer_numbers(offer_extracted)
            if offer_nums & offer_numbers:  # intersección no vacía
                return offer, MatchStrategy.EXACT_OFFER_NUMBER, 1.0

    # 2. CLIENT_LINES_SIMILARITY
    order_client = _normalize_client_name(
        (order_extracted.get("cliente") or {}).get("nombre")
    )
    order_refs = _line_refs(order_extracted)
    if not order_client or not order_refs:
        return None

    best: tuple[Document, float] | None = None
    candidates = _candidate_offers(session, tenant_id, exclude_doc_id=order_doc_id)
    for offer in candidates:
        offer_extracted = offer.extracted_json or {}
        offer_client = _normalize_client_name(
            (offer_extracted.get("cliente") or {}).get("nombre")
        )
        if not offer_client:
            continue
        # Cliente debe coincidir (substring bidireccional para tolerar variantes)
        if offer_client not in order_client and order_client not in offer_client:
            continue
        offer_refs = _line_refs(offer_extracted)
        if not offer_refs:
            continue
        intersection = order_refs & offer_refs
        union = order_refs | offer_refs
        score = len(intersection) / len(union) if union else 0.0
        if score >= MIN_LINES_SIMILARITY and (best is None or score > best[1]):
            best = (offer, score)

    if best is not None:
        return best[0], MatchStrategy.CLIENT_LINES_SIMILARITY, best[1]
    return None


def _candidate_offers(
    session: Session, tenant_id: UUID, *, exclude_doc_id: UUID
) -> list[Document]:
    """Ofertas del tenant que aún no están vinculadas a un pedido."""
    # session.exec con un single-column select devuelve scalars directamente
    linked_offer_ids = set(
        session.exec(
            select(DocumentLink.offer_document_id).where(
                DocumentLink.tenant_id == tenant_id
            )
        ).all()
    )
    query = select(Document).where(
        Document.tenant_id == tenant_id,
        Document.document_type == DocumentType.OFERTA,
        Document.id != exclude_doc_id,
    )
    return [d for d in session.exec(query).all() if d.id not in linked_offer_ids]


# =============================================================================
# Comparación de líneas
# =============================================================================


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compare_order_vs_offer(
    order_extracted: dict[str, Any],
    offer_extracted: dict[str, Any],
) -> dict[str, Any]:
    """Compara las líneas del pedido vs la oferta vinculada.

    Devuelve un dict con:
    - `lines_in_both[]`: ref común con datos de ambos lados + issues
    - `lines_only_in_order[]`: refs nuevas que el cliente añadió
    - `lines_only_in_offer[]`: refs de la oferta no pedidas
    - `summary`: contadores

    Issues por línea:
    - `price_changed`: precio fuera de tolerancia (5%)
    - `qty_changed`: cantidad distinta
    """
    order_lines = {
        normalize_reference(line.get("referencia") or ""): line
        for line in (order_extracted.get("lineas") or [])
        if isinstance(line, dict) and line.get("referencia")
    }
    offer_lines = {
        normalize_reference(line.get("referencia") or ""): line
        for line in (offer_extracted.get("lineas") or [])
        if isinstance(line, dict) and line.get("referencia")
    }

    common_refs = order_lines.keys() & offer_lines.keys()
    only_order_refs = order_lines.keys() - offer_lines.keys()
    only_offer_refs = offer_lines.keys() - order_lines.keys()

    lines_in_both: list[dict[str, Any]] = []
    price_disc = qty_disc = 0
    for ref in sorted(common_refs):
        ol = order_lines[ref]
        fl = offer_lines[ref]
        op = _to_float(ol.get("precio_unitario"))
        fp = _to_float(fl.get("precio_unitario"))
        oq = _to_float(ol.get("cantidad"))
        fq = _to_float(fl.get("cantidad"))
        issues: list[str] = []
        if (
            op is not None
            and fp is not None
            and fp > 0
            and abs(op - fp) / fp > PRICE_DIFF_TOLERANCE
        ):
            issues.append("price_changed")
            price_disc += 1
        if oq is not None and fq is not None and oq != fq:
            issues.append("qty_changed")
            qty_disc += 1
        lines_in_both.append(
            {
                "reference": ol.get("referencia"),
                "in_offer": {
                    "cantidad": fq,
                    "precio_unitario": fp,
                    "descripcion": fl.get("descripcion"),
                },
                "in_order": {
                    "cantidad": oq,
                    "precio_unitario": op,
                    "descripcion": ol.get("descripcion"),
                },
                "issues": issues,
            }
        )

    return {
        "lines_in_both": lines_in_both,
        "lines_only_in_order": [
            {
                "reference": order_lines[r].get("referencia"),
                "cantidad": _to_float(order_lines[r].get("cantidad")),
                "precio_unitario": _to_float(order_lines[r].get("precio_unitario")),
                "descripcion": order_lines[r].get("descripcion"),
            }
            for r in sorted(only_order_refs)
        ],
        "lines_only_in_offer": [
            {
                "reference": offer_lines[r].get("referencia"),
                "cantidad": _to_float(offer_lines[r].get("cantidad")),
                "precio_unitario": _to_float(offer_lines[r].get("precio_unitario")),
                "descripcion": offer_lines[r].get("descripcion"),
            }
            for r in sorted(only_offer_refs)
        ],
        "summary": {
            "common": len(common_refs),
            "added_in_order": len(only_order_refs),
            "removed_from_offer": len(only_offer_refs),
            "price_discrepancies": price_disc,
            "qty_discrepancies": qty_disc,
        },
    }
