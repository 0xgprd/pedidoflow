"""CRUD endpoints de Concept (diccionario unificado)."""

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import Session, or_, select

from app.api.deps import get_current_tenant_id
from app.core.db import get_session
from app.core.logging import get_logger
from app.models.concept import (
    SCHEMA_FIELD_PATHS,
    SCHEMA_FIELDS,
    Concept,
    ConceptCreate,
    ConceptRead,
    ConceptUpdate,
    normalize_alias,
)
from app.models.tenant_field import TenantField

log = get_logger(__name__)
router = APIRouter(prefix="/concepts", tags=["concepts"])


@router.get("/schema-fields")
def list_schema_fields(
    session: Annotated[Session, Depends(get_session)],
    x_tenant_id: Annotated[UUID | None, Header(alias="X-Tenant-Id")] = None,
) -> list[dict[str, Any]]:
    """Campos del esquema (fijos + custom del tenant si va el header).

    El frontend usa esta lista para:
    - El selector "asignar a campo" del PDF (modal AssignToConcept).
    - La página Memoria, agrupados por `group`.
    - El panel derecho de DocumentDetail (ver qué campos custom renderizar).
    """
    out: list[dict[str, Any]] = [
        {"path": p, "label": label, "group": group, "is_custom": False}
        for p, label, group in SCHEMA_FIELDS
    ]
    if x_tenant_id is not None:
        custom = list(
            session.exec(
                select(TenantField)
                .where(TenantField.tenant_id == x_tenant_id)
                .order_by(TenantField.group, TenantField.order, TenantField.label)  # type: ignore[arg-type]
            ).all()
        )
        for tf in custom:
            out.append(
                {
                    "path": tf.field_path,
                    "label": tf.label,
                    "group": tf.group,
                    "is_custom": True,
                    "tenant_field_id": str(tf.id),
                }
            )
    return out


@router.get("", response_model=list[ConceptRead])
def list_concepts(
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> list[Concept]:
    """Lista conceptos del tenant + globales (tenant_id IS NULL)."""
    query = (
        select(Concept)
        .where(or_(Concept.tenant_id == tenant_id, Concept.tenant_id.is_(None)))  # type: ignore[union-attr]
        .order_by(Concept.name)  # type: ignore[arg-type]
    )
    return list(session.exec(query).all())


def _is_valid_field_path(path: str, tenant_id: UUID, session: Session) -> bool:
    """Acepta los paths fijos del esquema o `custom.<key>` si existe TenantField."""
    if path in SCHEMA_FIELD_PATHS:
        return True
    if path.startswith("custom."):
        key = path.removeprefix("custom.")
        tf = session.exec(
            select(TenantField).where(TenantField.tenant_id == tenant_id, TenantField.key == key)
        ).first()
        return tf is not None
    return False


@router.post("", response_model=ConceptRead, status_code=status.HTTP_201_CREATED)
def create_concept(
    payload: ConceptCreate,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> Concept:
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="name vacío")

    # Validar field_path si se especifica
    if payload.field_path and not _is_valid_field_path(payload.field_path, tenant_id, session):
        raise HTTPException(
            status_code=400,
            detail=(
                f"field_path '{payload.field_path}' no existe. "
                "Debe ser uno de los fijos del esquema o un `custom.<key>` ya definido."
            ),
        )

    aliases_norm = list(
        dict.fromkeys(normalize_alias(a) for a in (payload.aliases or []) if normalize_alias(a))
    )

    concept = Concept(
        tenant_id=None if payload.is_global else tenant_id,
        name=payload.name.strip(),
        code=(payload.code or "").strip() or None,
        field_path=payload.field_path,
        aliases=aliases_norm,
    )
    session.add(concept)
    session.commit()
    session.refresh(concept)
    log.info(
        "concept.created",
        id=str(concept.id),
        tenant_id=str(concept.tenant_id) if concept.tenant_id else "GLOBAL",
        aliases=len(aliases_norm),
    )
    return concept


@router.patch("/{concept_id}", response_model=ConceptRead)
def update_concept(
    concept_id: UUID,
    payload: ConceptUpdate,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> Concept:
    c = session.get(Concept, concept_id)
    if c is None or (c.tenant_id is not None and c.tenant_id != tenant_id):
        raise HTTPException(status_code=404, detail="Concept not found")

    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        c.name = data["name"].strip()
    if "code" in data:
        c.code = (data["code"] or "").strip() or None
    if "field_path" in data:
        if data["field_path"] and not _is_valid_field_path(data["field_path"], tenant_id, session):
            raise HTTPException(status_code=400, detail="field_path inválido")
        c.field_path = data["field_path"] or None
    if "aliases" in data:
        c.aliases = list(
            dict.fromkeys(normalize_alias(a) for a in (data["aliases"] or []) if normalize_alias(a))
        )
        flag_modified(c, "aliases")
    if "is_global" in data:
        c.tenant_id = None if data["is_global"] else tenant_id
    c.updated_at = datetime.now(UTC)
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


@router.delete("/{concept_id}", status_code=204)
def delete_concept(
    concept_id: UUID,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    c = session.get(Concept, concept_id)
    if c is None or (c.tenant_id is not None and c.tenant_id != tenant_id):
        raise HTTPException(status_code=404, detail="Concept not found")
    session.delete(c)
    session.commit()


# =============================================================================
# Helper: añadir un alias a un concepto existente (atajo desde el PDF)
# =============================================================================


class AddAliasPayload(BaseModel):
    text: str


@router.post("/{concept_id}/aliases", response_model=ConceptRead)
def add_alias(
    concept_id: UUID,
    payload: AddAliasPayload,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> Concept:
    c = session.get(Concept, concept_id)
    if c is None or (c.tenant_id is not None and c.tenant_id != tenant_id):
        raise HTTPException(status_code=404, detail="Concept not found")
    norm = normalize_alias(payload.text)
    if not norm:
        raise HTTPException(status_code=400, detail="alias vacío")
    if norm not in c.aliases:
        c.aliases = [*c.aliases, norm]
        flag_modified(c, "aliases")
        c.updated_at = datetime.now(UTC)
        session.add(c)
        session.commit()
        session.refresh(c)
    return c
