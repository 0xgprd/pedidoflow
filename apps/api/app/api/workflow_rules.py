"""CRUD endpoints de WorkflowRule per-tenant + endpoint de prueba."""

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_current_tenant_id
from app.core.db import get_session
from app.core.logging import get_logger
from app.models.workflow_rule import (
    WorkflowRule,
    WorkflowRuleCreate,
    WorkflowRuleRead,
    WorkflowRuleUpdate,
)
from app.services.rules_engine import evaluate_rules

log = get_logger(__name__)
router = APIRouter(prefix="/workflow-rules", tags=["workflow-rules"])


@router.get("", response_model=list[WorkflowRuleRead])
def list_rules(
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> list[WorkflowRule]:
    return list(
        session.exec(
            select(WorkflowRule)
            .where(WorkflowRule.tenant_id == tenant_id)
            .order_by(WorkflowRule.priority, WorkflowRule.created_at)  # type: ignore[arg-type]
        ).all()
    )


@router.post("", response_model=WorkflowRuleRead, status_code=status.HTTP_201_CREATED)
def create_rule(
    payload: WorkflowRuleCreate,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> WorkflowRule:
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="name vacío")
    if not payload.conditions:
        raise HTTPException(status_code=400, detail="conditions vacío (al menos 1)")

    rule = WorkflowRule(
        tenant_id=tenant_id,
        name=payload.name.strip(),
        description=payload.description,
        enabled=payload.enabled,
        priority=payload.priority,
        scope=payload.scope,
        conditions=payload.conditions,
        action=payload.action,
        action_params=payload.action_params,
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)
    log.info("workflow_rule.created", id=str(rule.id), tenant_id=str(tenant_id))
    return rule


@router.patch("/{rule_id}", response_model=WorkflowRuleRead)
def update_rule(
    rule_id: UUID,
    payload: WorkflowRuleUpdate,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> WorkflowRule:
    rule = session.get(WorkflowRule, rule_id)
    if rule is None or rule.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Rule not found")

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(rule, k, v)
    rule.updated_at = datetime.now(UTC)
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=204)
def delete_rule(
    rule_id: UUID,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    rule = session.get(WorkflowRule, rule_id)
    if rule is None or rule.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Rule not found")
    session.delete(rule)
    session.commit()


# =============================================================================
# Endpoint de prueba: evalúa una regla contra un JSON arbitrario sin guardarla
# =============================================================================


class TestRulePayload(BaseModel):
    rule: WorkflowRuleCreate
    extracted_json: dict[str, Any]
    document_type: str = "pedido"


@router.post("/test")
def test_rule(
    payload: TestRulePayload,
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
) -> dict[str, Any]:
    """Evalúa una regla provisional contra un JSON sin persistir.

    Útil para que el editor de reglas muestre preview en tiempo real.
    """
    fake_rule = WorkflowRule(
        tenant_id=tenant_id,
        name=payload.rule.name,
        enabled=True,
        priority=0,
        scope=payload.rule.scope,
        conditions=payload.rule.conditions,
        action=payload.rule.action,
        action_params=payload.rule.action_params,
    )
    result = evaluate_rules([fake_rule], payload.extracted_json, document_type=payload.document_type)
    # Quitar campos internos
    result.pop("_matched_uuid_ids", None)
    return result
