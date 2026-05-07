"""CRUD del catálogo de referencias per-tenant + upload CSV."""

import csv
import io
import re
import unicodedata
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_current_tenant_id
from app.core.db import get_session
from app.core.logging import get_logger
from app.models.catalog_item import (
    CatalogItem,
    CatalogItemCreate,
    CatalogItemRead,
    CatalogItemUpdate,
    normalize_reference,
)

log = get_logger(__name__)
router = APIRouter(prefix="/catalog-items", tags=["catalog"])


@router.get("", response_model=list[CatalogItemRead])
def list_items(
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
    search: Annotated[str | None, Query(description="Buscar por ref o descripción")] = None,
    active_only: Annotated[bool, Query()] = True,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CatalogItem]:
    query = select(CatalogItem).where(CatalogItem.tenant_id == tenant_id)
    if active_only:
        query = query.where(CatalogItem.active.is_(True))  # type: ignore[union-attr]
    if search:
        norm = normalize_reference(search)
        # Match en ref normalizada O substring en descripción
        from sqlalchemy import func, or_

        query = query.where(
            or_(
                CatalogItem.reference_normalized.like(f"%{norm}%"),  # type: ignore[union-attr]
                func.upper(CatalogItem.description).like(f"%{norm}%"),
            )
        )
    # Orden: sort_order ASC (preserva el orden de la tarifa al subir CSV) y
    # como tiebreaker la referencia normalizada (alfabético dentro de un mismo grupo).
    query = (
        query.order_by(CatalogItem.sort_order, CatalogItem.reference_normalized)  # type: ignore[attr-defined]
        .offset(offset)
        .limit(limit)
    )
    return list(session.exec(query).all())


@router.post("", response_model=CatalogItemRead, status_code=status.HTTP_201_CREATED)
def upsert_item(
    payload: CatalogItemCreate,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> CatalogItem:
    """Crea o actualiza una referencia (upsert por (tenant, reference_normalized))."""
    norm = normalize_reference(payload.reference)
    if not norm:
        raise HTTPException(status_code=400, detail="reference vacío")

    existing = session.exec(
        select(CatalogItem).where(
            CatalogItem.tenant_id == tenant_id,
            CatalogItem.reference_normalized == norm,
        )
    ).first()

    if existing is not None:
        existing.reference = payload.reference
        existing.description = payload.description
        existing.unit = payload.unit
        existing.min_price = payload.min_price
        existing.list_price = payload.list_price
        existing.currency = payload.currency
        existing.active = payload.active
        existing.notes = payload.notes
        existing.updated_at = datetime.now(UTC)
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    item = CatalogItem(
        tenant_id=tenant_id,
        reference=payload.reference,
        reference_normalized=norm,
        description=payload.description,
        unit=payload.unit,
        min_price=payload.min_price,
        list_price=payload.list_price,
        currency=payload.currency,
        active=payload.active,
        notes=payload.notes,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.patch("/{item_id}", response_model=CatalogItemRead)
def update_item(
    item_id: UUID,
    payload: CatalogItemUpdate,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> CatalogItem:
    item = session.get(CatalogItem, item_id)
    if item is None or item.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Item not found")

    data = payload.model_dump(exclude_unset=True)
    if "reference" in data:
        item.reference = data["reference"]
        item.reference_normalized = normalize_reference(data["reference"])
    for field in ("description", "unit", "min_price", "list_price", "currency", "active", "notes"):
        if field in data:
            setattr(item, field, data[field])
    item.updated_at = datetime.now(UTC)
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(
    item_id: UUID,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    item = session.get(CatalogItem, item_id)
    if item is None or item.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Item not found")
    session.delete(item)
    session.commit()


# =============================================================================
# Upload CSV
# =============================================================================


class UploadResult(BaseModel):
    created: int
    updated: int
    skipped: int
    errors: list[str]


# Aliases de columna → campo canónico. Match case-insensitive y sin acentos.
# Soporta español, inglés y francés (Quimilock comercia en FR).
_COLUMN_ALIASES: dict[str, list[str]] = {
    "reference": ["reference", "ref", "referencia", "codigo", "code", "sku"],
    "description": ["description", "descripcion", "desc", "designation", "nombre", "name"],
    "unit": ["unit", "unidad", "ud", "uom"],
    "min_price": [
        "min_price",
        "precio minimo",
        "precio_minimo",
        "minimo",
        "precio unitario",
        "precio_unitario",
        "precio",
        "price",
        "prix",
    ],
    "list_price": [
        "list_price",
        "precio lista",
        "precio_lista",
        "precio publico",
        "list price",
        "tarifa",
    ],
    "currency": ["currency", "moneda", "devise"],
    "active": ["active", "activa", "activo", "actif"],
    "notes": ["notes", "notas", "observaciones", "remarks", "remarques"],
}


def _norm_header(h: str) -> str:
    """Normaliza un header: trim + lowercase + sin acentos + colapsa espacios."""
    s = h.strip().lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.split())


def _build_header_map(fieldnames: list[str]) -> dict[str, str]:
    """Devuelve mapa {campo_canonico: nombre_columna_real_en_csv}."""
    by_norm = {_norm_header(f): f for f in fieldnames}
    out: dict[str, str] = {}
    for canonical, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            real = by_norm.get(alias)
            if real is not None:
                out[canonical] = real
                break
    return out


def _parse_decimal(s: str | None) -> Decimal | None:
    """Parsea un decimal. Acepta `€8,20`, `$ 8.20`, `8,20`, `8.20`, `1.234,56`."""
    if not s:
        return None
    # Quitar símbolos de moneda y otros caracteres no numéricos
    cleaned = re.sub(r"[^\d,.\-]", "", s)
    if not cleaned:
        return None
    # Heurística europea vs americana: si tiene "," como último separador → coma decimal
    if "," in cleaned and "." in cleaned:
        # "1.234,56" → quitar . de miles y cambiar , por .
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def _parse_bool(s: str | None) -> bool:
    if not s:
        return True
    return s.lower() in ("true", "1", "si", "sí", "yes", "y", "x", "active", "actif")


@router.post("/upload", response_model=UploadResult)
async def upload_csv(
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
    file: Annotated[
        UploadFile,
        File(
            description="CSV con columnas: reference, description, unit, min_price, list_price, currency, active, notes (acepta alias en español/francés)"
        ),
    ],
) -> UploadResult:
    """Importa un catálogo desde CSV.

    Columnas reconocidas (case-insensitive, sin acentos, en es/en/fr):
    - reference / ref / referencia / codigo / sku        (REQUERIDA)
    - description / descripcion / nombre / designation
    - unit / unidad / ud
    - min_price / precio minimo / precio unitario / precio / prix
    - list_price / precio lista / tarifa
    - currency / moneda / devise   (default EUR)
    - active / activa / actif      (default true)
    - notes / notas / observaciones

    Precios: acepta `€8,20`, `8.20`, `1.234,56`, `$ 8.20`, etc.
    Si una `reference` ya existe, se actualiza.
    """
    if not file.filename or not file.filename.lower().endswith((".csv", ".txt")):
        raise HTTPException(status_code=400, detail="Sube un fichero .csv")

    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("latin-1")
        except UnicodeDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Encoding no soportado: {e}") from e

    # Detectar delimitador (coma, ; o tab)
    sniffer = csv.Sniffer()
    sample = text[:2048]
    try:
        dialect = sniffer.sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)

    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV vacío")

    header_map = _build_header_map(list(reader.fieldnames))
    if "reference" not in header_map:
        raise HTTPException(
            status_code=400,
            detail=(
                "CSV debe tener una columna de referencia (alias aceptados: "
                "reference, ref, referencia, codigo, sku). "
                f"Encontradas: {', '.join(reader.fieldnames)}"
            ),
        )

    def get(row: dict, key: str) -> str | None:
        col = header_map.get(key)
        if col is None:
            return None
        v = row.get(col)
        return v.strip() if isinstance(v, str) and v.strip() else None

    created = updated = skipped = 0
    errors: list[str] = []

    for i, row in enumerate(reader, start=2):
        ref = get(row, "reference")
        if not ref:
            skipped += 1
            continue
        norm = normalize_reference(ref)

        existing = session.exec(
            select(CatalogItem).where(
                CatalogItem.tenant_id == tenant_id,
                CatalogItem.reference_normalized == norm,
            )
        ).first()

        try:
            data = {
                "reference": ref,
                "reference_normalized": norm,
                "description": get(row, "description"),
                "unit": get(row, "unit"),
                "min_price": _parse_decimal(get(row, "min_price")),
                "list_price": _parse_decimal(get(row, "list_price")),
                "currency": get(row, "currency") or "EUR",
                "active": _parse_bool(get(row, "active")),
                "notes": get(row, "notes"),
            }
            if existing is not None:
                for k, v in data.items():
                    setattr(existing, k, v)
                existing.updated_at = datetime.now(UTC)
                session.add(existing)
                updated += 1
            else:
                session.add(CatalogItem(tenant_id=tenant_id, **data))
                created += 1
        except Exception as e:
            errors.append(f"línea {i} ({ref}): {e}")
            skipped += 1

    session.commit()
    log.info(
        "catalog.upload",
        tenant_id=str(tenant_id),
        created=created,
        updated=updated,
        skipped=skipped,
        columns_mapped=list(header_map.keys()),
    )
    return UploadResult(created=created, updated=updated, skipped=skipped, errors=errors[:20])
