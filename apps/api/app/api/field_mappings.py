"""CRUD endpoints de FieldMapping (memoria/aprendizaje per-tenant)."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.api.deps import get_current_tenant_id
from app.core.db import get_session
from app.core.logging import get_logger
from app.models.field_mapping import (
    FieldMapping,
    FieldMappingCreate,
    FieldMappingRead,
    FieldMappingUpdate,
    normalize_source_text,
)

log = get_logger(__name__)
router = APIRouter(prefix="/field-mappings", tags=["field-mappings"])


@router.get("", response_model=list[FieldMappingRead])
def list_mappings(
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> list[FieldMapping]:
    return list(
        session.exec(
            select(FieldMapping)
            .where(FieldMapping.tenant_id == tenant_id)
            .order_by(FieldMapping.hits.desc(), FieldMapping.created_at.desc())  # type: ignore[attr-defined]
        ).all()
    )


@router.post("", response_model=FieldMappingRead, status_code=status.HTTP_201_CREATED)
def upsert_mapping(
    payload: FieldMappingCreate,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> FieldMapping:
    """Crea o actualiza un mapping (upsert por (tenant_id, source_text_normalized))."""
    norm = normalize_source_text(payload.source_text)
    if not norm:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="source_text vacío")
    if not payload.canonical_value.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="canonical_value vacío"
        )

    existing = session.exec(
        select(FieldMapping).where(
            FieldMapping.tenant_id == tenant_id,
            FieldMapping.source_text_normalized == norm,
        )
    ).first()

    if existing is not None:
        existing.source_text = payload.source_text
        existing.canonical_value = payload.canonical_value.strip()
        existing.canonical_code = (payload.canonical_code or None) and payload.canonical_code.strip()
        existing.field_path_pattern = (payload.field_path_pattern or None) and payload.field_path_pattern.strip()
        existing.updated_at = datetime.now(UTC)
        session.add(existing)
        session.commit()
        session.refresh(existing)
        log.info("field_mapping.updated", id=str(existing.id), tenant_id=str(tenant_id))
        return existing

    mapping = FieldMapping(
        tenant_id=tenant_id,
        source_text=payload.source_text,
        source_text_normalized=norm,
        canonical_value=payload.canonical_value.strip(),
        canonical_code=(payload.canonical_code or None) and payload.canonical_code.strip(),
        field_path_pattern=(payload.field_path_pattern or None)
        and payload.field_path_pattern.strip(),
    )
    session.add(mapping)
    session.commit()
    session.refresh(mapping)
    log.info("field_mapping.created", id=str(mapping.id), tenant_id=str(tenant_id))
    return mapping


@router.patch("/{mapping_id}", response_model=FieldMappingRead)
def update_mapping(
    mapping_id: UUID,
    payload: FieldMappingUpdate,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> FieldMapping:
    m = session.get(FieldMapping, mapping_id)
    if m is None or m.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found")

    if payload.canonical_value is not None:
        if not payload.canonical_value.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="canonical_value vacío"
            )
        m.canonical_value = payload.canonical_value.strip()
    if payload.canonical_code is not None:
        m.canonical_code = payload.canonical_code.strip() or None
    if payload.field_path_pattern is not None:
        m.field_path_pattern = payload.field_path_pattern.strip() or None
    m.updated_at = datetime.now(UTC)
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


@router.delete("/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mapping(
    mapping_id: UUID,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    m = session.get(FieldMapping, mapping_id)
    if m is None or m.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found")
    session.delete(m)
    session.commit()
