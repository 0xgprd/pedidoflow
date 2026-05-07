"""CRUD de campos custom per-tenant (extienden los grupos del esquema)."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.api.deps import get_current_tenant_id
from app.core.db import get_session
from app.core.logging import get_logger
from app.models.concept import Concept
from app.models.tenant_field import (
    ALLOWED_GROUPS,
    TenantField,
    TenantFieldCreate,
    TenantFieldRead,
    TenantFieldUpdate,
    slugify_key,
    validate_key,
)

log = get_logger(__name__)
router = APIRouter(prefix="/tenant-fields", tags=["tenant-fields"])


def _to_read(tf: TenantField) -> TenantFieldRead:
    return TenantFieldRead(
        id=tf.id,
        tenant_id=tf.tenant_id,
        group=tf.group,
        key=tf.key,
        label=tf.label,
        description=tf.description,
        order=tf.order,
        field_path=tf.field_path,
        created_at=tf.created_at,
        updated_at=tf.updated_at,
    )


@router.get("", response_model=list[TenantFieldRead])
def list_tenant_fields(
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> list[TenantFieldRead]:
    rows = list(
        session.exec(
            select(TenantField)
            .where(TenantField.tenant_id == tenant_id)
            .order_by(TenantField.group, TenantField.order, TenantField.label)  # type: ignore[arg-type]
        ).all()
    )
    return [_to_read(r) for r in rows]


@router.post("", response_model=TenantFieldRead, status_code=status.HTTP_201_CREATED)
def create_tenant_field(
    payload: TenantFieldCreate,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> TenantFieldRead:
    if payload.group not in ALLOWED_GROUPS:
        raise HTTPException(
            status_code=400,
            detail=f"group inválido. Permitidos: {sorted(ALLOWED_GROUPS)}",
        )
    label = payload.label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="label vacío")

    key = (payload.key or slugify_key(label)).strip().lower()
    if not key or not validate_key(key):
        raise HTTPException(
            status_code=400,
            detail="key inválida (snake_case, empieza por letra, máx 50 chars)",
        )

    # Único por tenant
    dup = session.exec(
        select(TenantField).where(TenantField.tenant_id == tenant_id, TenantField.key == key)
    ).first()
    if dup is not None:
        raise HTTPException(status_code=409, detail=f"Ya existe un campo con key '{key}'")

    tf = TenantField(
        tenant_id=tenant_id,
        group=payload.group,
        key=key,
        label=label,
        description=(payload.description or "").strip() or None,
        order=payload.order,
    )
    session.add(tf)
    session.commit()
    session.refresh(tf)
    log.info(
        "tenant_field.created",
        id=str(tf.id),
        tenant_id=str(tenant_id),
        key=key,
        group=payload.group,
    )
    return _to_read(tf)


@router.patch("/{field_id}", response_model=TenantFieldRead)
def update_tenant_field(
    field_id: UUID,
    payload: TenantFieldUpdate,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> TenantFieldRead:
    tf = session.get(TenantField, field_id)
    if tf is None or tf.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="TenantField not found")

    data = payload.model_dump(exclude_unset=True)
    if "label" in data and data["label"]:
        tf.label = data["label"].strip()
    if "description" in data:
        tf.description = (data["description"] or "").strip() or None
    if "order" in data and data["order"] is not None:
        tf.order = int(data["order"])
    tf.updated_at = datetime.now(UTC)
    session.add(tf)
    session.commit()
    session.refresh(tf)
    return _to_read(tf)


@router.delete("/{field_id}", status_code=204)
def delete_tenant_field(
    field_id: UUID,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    tf = session.get(TenantField, field_id)
    if tf is None or tf.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="TenantField not found")

    field_path = tf.field_path
    # Cascada: borrar Concepts del tenant que apuntaban a este field_path
    concepts = list(
        session.exec(
            select(Concept).where(
                Concept.tenant_id == tenant_id,
                Concept.field_path == field_path,
            )
        ).all()
    )
    for c in concepts:
        session.delete(c)
    session.delete(tf)
    session.commit()
    log.info(
        "tenant_field.deleted",
        id=str(field_id),
        field_path=field_path,
        cascade_concepts=len(concepts),
    )
