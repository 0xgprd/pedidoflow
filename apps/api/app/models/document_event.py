"""Audit log de acciones sobre un Document.

Cada evento queda como un row inmutable: quién hizo qué, cuándo y con qué
datos. Es la fuente de verdad para la pestaña "Historial" del documento y
para auditoría posterior.

Diseño:
- INSERT-only — nunca se actualiza ni se borra (excepto cascade al borrar
  documento). Hace que el historial sea fiable.
- `actor_email` se guarda como STRING separado del FK por dos razones:
    1. Si un user se borra de auth.users, el evento sigue diciendo quién lo hizo.
    2. Permite eventos automáticos (worker, sistema) con actor_email=None y
       una etiqueta "system" en `actor_label`.
- `event_data` es JSONB libre para detalles específicos del tipo de evento
  (e.g. {"erp_id": "SAL-ORD-..."} para `pushed_to_erp`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


class DocumentEventType(StrEnum):
    """Tipos de eventos sobre un documento.

    SOLO acciones humanas — lo que hace la IA / worker / polling NO se
    traza aquí (queda implícito en `Document.created_at` y
    `Document.processed_at`). El audit log mide cuánto tarda un humano en
    intervenir y qué decisiones toma sobre el documento.

    Lista cerrada — añadir nuevos valores requiere actualizar también la UI
    para que renderice un icono/copy adecuado.
    """

    # Carga manual (no la del polling de Outlook que es automática)
    UPLOADED = "uploaded"  # alguien subió un PDF manualmente
    REPROCESSED = "reprocessed"  # alguien volvió a encolar la extracción

    # Edición / clasificación
    TYPE_CHANGED = "type_changed"  # alguien cambió pedido↔oferta↔ficha...
    EXTRACTED_EDITED = "extracted_edited"  # alguien editó campos extraídos

    # Vinculación pedido↔oferta (solo manual — el auto-match del worker NO se traza)
    LINKED_TO_OFFER = "linked_to_offer"
    UNLINKED_FROM_OFFER = "unlinked_from_offer"

    # Cambio de estado (aprobación/rechazo)
    APPROVED = "approved"
    REJECTED = "rejected"
    REOPENED = "reopened"  # vuelta de approved/rejected a extracted

    # Acciones contra ERP — siempre disparadas por humano clickeando
    PUSHED_TO_ERP = "pushed_to_erp"
    PUSH_TO_ERP_FAILED = "push_to_erp_failed"
    CUSTOMER_REGISTERED = "customer_registered"
    CUSTOMER_REGISTER_FAILED = "customer_register_failed"


class DocumentEvent(SQLModel, table=True):
    """Audit row: una acción sobre un document, con quién y cuándo."""

    __tablename__ = "document_events"
    __table_args__ = (Index("ix_document_events_document_created", "document_id", "created_at"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    # Tenant para defense-in-depth (las queries del audit log siempre filtran por tenant).
    tenant_id: UUID = Field(foreign_key="tenants.id", index=True, nullable=False)

    # Document referenciado. Cascade delete: si se borra el doc, su historial se va con él.
    document_id: UUID = Field(
        foreign_key="documents.id", nullable=False, index=True, ondelete="CASCADE"
    )

    event_type: DocumentEventType = Field(nullable=False, index=True)

    # Actor — quién disparó la acción. Tres casos:
    #   1. Usuario humano vía UI/API → email + user_id del JWT
    #   2. Sistema (worker, polling automático) → actor_email=None, actor_label="system"
    #   3. Usuario eliminado posteriormente → user_id puede ser stale, email persiste
    actor_email: str | None = Field(default=None, max_length=320)
    actor_user_id: UUID | None = Field(default=None)
    actor_label: str | None = Field(
        default=None,
        max_length=50,
        description="Etiqueta legible: 'system', 'worker', o nombre del usuario",
    )

    # Datos específicos del evento (campos varían por event_type).
    event_data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON().with_variant(JSONB(), "postgresql")),
    )

    # Sin updated_at — los eventos son inmutables.
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )


class DocumentEventRead(SQLModel):
    """Schema de salida para la API."""

    id: UUID
    document_id: UUID
    event_type: DocumentEventType
    actor_email: str | None
    actor_user_id: UUID | None
    actor_label: str | None
    event_data: dict[str, Any]
    created_at: datetime
