"""DocumentLink = vínculo entre un pedido y su oferta original.

Reglas (ver memory/project_quimilock_workflow.md):
- Las ofertas las emite Quimilock (formato `TL[YYMMDD]-[NC]`).
- El cliente devuelve un pedido que a veces lleva el nº de oferta, a veces no.
- Cuando llega un PEDIDO, intentamos vincularlo:
    1. exact match por nº de oferta (si el pedido lo declara)
    2. similaridad de líneas (mismo cliente + refs comunes)
    3. manual (botón en UI)

Los resultados de la comparación se guardan en `comparison_result` como JSONB
para verlos en la UI sin re-calcular.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin


class MatchStrategy(StrEnum):
    EXACT_OFFER_NUMBER = "exact_offer_number"
    CLIENT_LINES_SIMILARITY = "client_lines_similarity"
    MANUAL = "manual"


class DocumentLink(TimestampMixin, table=True):
    """Vínculo pedido → oferta. Un pedido tiene como mucho 1 oferta vinculada."""

    __tablename__ = "document_links"
    __table_args__ = (
        UniqueConstraint("order_document_id", name="uq_document_links_order"),
        Index("ix_document_links_tenant_offer", "tenant_id", "offer_document_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(foreign_key="tenants.id", index=True, nullable=False)

    order_document_id: UUID = Field(foreign_key="documents.id", nullable=False)
    offer_document_id: UUID = Field(foreign_key="documents.id", nullable=False)

    match_strategy: MatchStrategy = Field(nullable=False)
    match_score: float = Field(default=0.0, nullable=False)  # 0..1
    comparison_result: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON().with_variant(JSONB(), "postgresql")),
    )


class DocumentLinkRead(SQLModel):
    id: UUID
    tenant_id: UUID
    order_document_id: UUID
    offer_document_id: UUID
    match_strategy: MatchStrategy
    match_score: float
    comparison_result: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
