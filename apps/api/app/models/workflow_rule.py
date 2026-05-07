"""WorkflowRule = regla de negocio per-tenant aplicada post-extracción.

Modelo declarativo (estilo Airtable filters):
- `conditions`: lista de condiciones AND. Cada una tiene `field`, `operator`, `value`.
- `action`: qué hacer si TODAS las condiciones se cumplen (block, warn, set_status...)

Ejemplo: bloquear pedidos < 2500€ sin línea de transporte
{
    "name": "Transporte obligatorio bajo 2500€",
    "conditions": [
        {"field": "totales.subtotal_ht", "operator": "lt", "value": 2500},
        {"field": "lineas.any.descripcion", "operator": "not_contains", "value": "transporte"}
    ],
    "action": "block",
    "action_params": {"message": "Pedidos < 2500€ deben incluir línea de transporte"}
}

El motor evalúa todas las reglas activas y guarda los hits en
`extracted_json.workflow` para que la UI muestre avisos/bloqueos.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin


class RuleAction(StrEnum):
    BLOCK = "block"          # impide aprobación
    WARN = "warn"            # solo aviso
    SET_STATUS = "set_status"  # cambia status automáticamente
    ADD_NOTE = "add_note"    # añade nota visible


class RuleScope(StrEnum):
    """Sobre qué tipo de documento se aplica."""

    ALL = "all"
    PEDIDO = "pedido"
    OFERTA = "oferta"


class WorkflowRule(TimestampMixin, table=True):
    """Regla de workflow per-tenant."""

    __tablename__ = "workflow_rules"
    __table_args__ = (
        Index("ix_workflow_rules_tenant_enabled", "tenant_id", "enabled"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(foreign_key="tenants.id", index=True, nullable=False)

    name: str = Field(max_length=200, nullable=False)
    description: str | None = Field(default=None, max_length=500)
    enabled: bool = Field(default=True, nullable=False)
    priority: int = Field(default=100, nullable=False)  # menor = se evalúa antes

    scope: RuleScope = Field(default=RuleScope.PEDIDO, nullable=False)

    # Lista de condiciones AND. Cada item: {field, operator, value, [case_insensitive]}
    conditions: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False),
    )

    action: RuleAction = Field(default=RuleAction.WARN, nullable=False)
    # Parámetros opcionales según acción: {message, status, ...}
    action_params: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False),
    )

    hits: int = Field(default=0, nullable=False)


class WorkflowRuleRead(SQLModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    enabled: bool
    priority: int
    scope: RuleScope
    conditions: list[dict[str, Any]]
    action: RuleAction
    action_params: dict[str, Any]
    hits: int
    created_at: datetime
    updated_at: datetime


class WorkflowRuleCreate(SQLModel):
    name: str
    description: str | None = None
    enabled: bool = True
    priority: int = 100
    scope: RuleScope = RuleScope.PEDIDO
    conditions: list[dict[str, Any]]
    action: RuleAction = RuleAction.WARN
    action_params: dict[str, Any] = Field(default_factory=dict)


class WorkflowRuleUpdate(SQLModel):
    name: str | None = None
    description: str | None = None
    enabled: bool | None = None
    priority: int | None = None
    scope: RuleScope | None = None
    conditions: list[dict[str, Any]] | None = None
    action: RuleAction | None = None
    action_params: dict[str, Any] | None = None
