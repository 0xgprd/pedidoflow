"""Aplicación de FieldMapping al JSON extraído.

Walk recursivo del JSON: para cada string value, busca si algún mapping aplica
(substring case-insensitive del `source_text_normalized` dentro del valor) y
reemplaza el valor entero por el `canonical_value` del mapping (con código entre
paréntesis si tiene `canonical_code`).

Reglas:
- Match case-insensitive y trim. "FREIGHT COST" matchea con "FREIGHT cost", " freight cost ", etc.
- Mappings más específicos (source_text más largo) tienen prioridad.
- `field_path_pattern` (glob, ej "lineas.*.descripcion") opcional para limitar dónde aplica.
- El bloque `source_texts` se preserva intacto (es el texto original del PDF para overlay).
"""

from __future__ import annotations

import fnmatch
from typing import Any
from uuid import UUID

from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import Session

from app.core.logging import get_logger
from app.models.field_mapping import FieldMapping, normalize_source_text

log = get_logger(__name__)


def apply_mappings(
    extracted_json: dict[str, Any],
    mappings: list[FieldMapping],
) -> tuple[dict[str, Any], set[UUID]]:
    """Aplica mappings al JSON. Devuelve (json_canonicalizado, ids_de_mappings_aplicados).

    No modifica el JSON original — retorna una copia transformada.
    """
    if not mappings:
        return extracted_json, set()

    # Más específicos primero (source_text más largo gana ante ambigüedad)
    sorted_mappings = sorted(
        mappings, key=lambda m: len(m.source_text_normalized), reverse=True
    )
    hit_ids: set[UUID] = set()

    def render(mapping: FieldMapping) -> str:
        if mapping.canonical_code:
            return f"{mapping.canonical_value} ({mapping.canonical_code})"
        return mapping.canonical_value

    def match(value: str, path: str) -> str | None:
        norm_value = normalize_source_text(value)
        if not norm_value:
            return None
        for m in sorted_mappings:
            if m.field_path_pattern and not fnmatch.fnmatch(path, m.field_path_pattern):
                continue
            if m.source_text_normalized in norm_value:
                hit_ids.add(m.id)
                return render(m)
        return None

    def walk(node: Any, path: str = "") -> Any:
        # Preservar source_texts: es el texto original del PDF para el overlay.
        if path == "source_texts":
            return node
        if isinstance(node, dict):
            return {k: walk(v, f"{path}.{k}" if path else k) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(item, f"{path}.{i}") for i, item in enumerate(node)]
        if isinstance(node, str):
            replacement = match(node, path)
            return replacement if replacement is not None else node
        return node

    result = walk(extracted_json)
    return result, hit_ids


def increment_hits(session: Session, mapping_ids: set[UUID]) -> None:
    """Incrementa el contador `hits` de los mappings aplicados."""
    if not mapping_ids:
        return
    for mid in mapping_ids:
        m = session.get(FieldMapping, mid)
        if m is not None:
            m.hits += 1
            flag_modified(m, "hits")
            session.add(m)
    session.commit()
    log.info("field_mappings.hits_incremented", count=len(mapping_ids))
