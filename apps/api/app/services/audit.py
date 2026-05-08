"""Helper de audit log para `DocumentEvent`.

SOLO trazamos acciones HUMANAS — la IA y el worker NO generan eventos en
el audit log. Su rastro queda en `Document.created_at` y `Document.processed_at`.

El caller pasa el `SupabaseUser` (o None si no hay user en el request,
como en el modo `X-Tenant-Id` fallback de dev). Si actor es None, se
trata como "anónimo" — el row queda sin email. En producción el usuario
siempre vendrá del JWT.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlmodel import Session

from app.core.auth import SupabaseUser
from app.core.logging import get_logger
from app.models.document import Document
from app.models.document_event import DocumentEvent, DocumentEventType

log = get_logger(__name__)


class Actor:
    """Quién hace una acción. Solo personas humanas que actúan vía UI/API."""

    __slots__ = ("email", "user_id", "label")

    def __init__(
        self,
        *,
        email: str | None = None,
        user_id: UUID | None = None,
        label: str | None = None,
    ) -> None:
        self.email = email
        self.user_id = user_id
        self.label = label

    @classmethod
    def from_user(cls, user: SupabaseUser | None) -> Actor:
        """Construye desde el SupabaseUser del JWT. None → anónimo (dev)."""
        if user is None:
            return cls(label="anonymous")
        return cls(
            email=user.email,
            user_id=user.id,
            label=user.email,
        )


def record_event(
    session: Session,
    document: Document,
    *,
    event_type: DocumentEventType,
    actor: Actor,
    event_data: dict[str, Any] | None = None,
    commit: bool = True,
) -> DocumentEvent:
    """Registra un evento en el audit log.

    No lanza excepciones — si el insert falla por cualquier razón, lo logueamos
    pero NO interrumpimos el flujo principal. La trazabilidad es importante
    pero NUNCA debe romper la operación de negocio.

    `commit=False` cuando el caller quiere agrupar varios eventos en una
    misma transacción.
    """
    event = DocumentEvent(
        tenant_id=document.tenant_id,
        document_id=document.id,
        event_type=event_type,
        actor_email=actor.email,
        actor_user_id=actor.user_id,
        actor_label=actor.label,
        event_data=event_data or {},
    )
    try:
        session.add(event)
        if commit:
            session.commit()
        log.info(
            "audit.event",
            document_id=str(document.id),
            event_type=event_type.value,
            actor=actor.label or actor.email or "anonymous",
        )
    except Exception as e:
        log.warning(
            "audit.event_persist_failed",
            document_id=str(document.id),
            event_type=event_type.value,
            error=str(e),
        )
        session.rollback()
    return event
