"""Aplica Concepts (substring case-insensitive) sobre extracted_json.

Para cada string del JSON, busca si contiene algún alias de algún concepto.
Si match → reemplaza el string por `name (code)` o `name`.

Reglas:
- Match case-insensitive y trim.
- Aliases más largos ganan ante ambigüedad (más específico = mejor).
- El bloque `source_texts` y `validation`/`workflow` se preservan intactos.
- Concepts globales (tenant_id=NULL) y per-tenant se mezclan.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import Session

from app.core.logging import get_logger
from app.models.concept import Concept, normalize_alias, render_concept

log = get_logger(__name__)

PROTECTED_PATHS = {"source_texts", "validation", "workflow", "custom_fields", "custom"}


def apply_concepts(
    extracted_json: dict[str, Any],
    concepts: list[Concept],
) -> tuple[dict[str, Any], set[UUID]]:
    """Devuelve (json_canonicalizado, ids_de_concepts_aplicados)."""
    if not concepts:
        return extracted_json, set()

    # (concept, alias_normalized) flatten + ordenar por longitud DESC
    pairs: list[tuple[str, Concept]] = []
    for c in concepts:
        for a in c.aliases or []:
            norm = normalize_alias(a)
            if norm:
                pairs.append((norm, c))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)

    hit_ids: set[UUID] = set()

    def match(value: str) -> str | None:
        norm = normalize_alias(value)
        if not norm:
            return None
        for alias_norm, concept in pairs:
            if alias_norm in norm:
                hit_ids.add(concept.id)
                return render_concept(concept)
        return None

    def walk(node: Any, path_first: str = "") -> Any:
        if path_first in PROTECTED_PATHS:
            return node
        if isinstance(node, dict):
            return {k: walk(v, path_first or k) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(item, path_first) for item in node]
        if isinstance(node, str):
            replacement = match(node)
            return replacement if replacement is not None else node
        return node

    return walk(extracted_json), hit_ids


def increment_hits(session: Session, concept_ids: set[UUID]) -> None:
    if not concept_ids:
        return
    for cid in concept_ids:
        c = session.get(Concept, cid)
        if c is not None:
            c.hits += 1
            flag_modified(c, "hits")
            session.add(c)
    session.commit()
    log.info("concepts.hits_incremented", count=len(concept_ids))
