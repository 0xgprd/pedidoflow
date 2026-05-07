"""EmailIntegration = conexión OAuth de un tenant a un buzón (Outlook/Gmail/etc).

Cada tenant puede conectar uno o más buzones. El worker polls la carpeta watched
periódicamente (cada N min) y por cada email no procesado:
- Descarga adjuntos PDF
- Crea Document(source="email", source_email=From) por cada PDF
- Encola extracción

Para webhook real (Microsoft Graph subscriptions) en lugar de polling, se hará
en producción cuando haya HTTPS público.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin


class IntegrationProvider(StrEnum):
    OUTLOOK = "outlook"
    GMAIL = "gmail"  # futuro


class IntegrationStatus(StrEnum):
    PENDING = "pending"     # OAuth iniciado, esperando callback
    ACTIVE = "active"       # token válido, polling activo
    EXPIRED = "expired"     # refresh token caducado, hay que reconectar
    ERROR = "error"         # error persistente (ver last_error)
    DISABLED = "disabled"   # desactivado por el usuario


class EmailIntegration(TimestampMixin, table=True):
    """Conexión OAuth a un buzón de email per-tenant."""

    __tablename__ = "email_integrations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", "email", name="uq_email_integration_tenant_email"),
        Index("ix_email_integration_tenant", "tenant_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(foreign_key="tenants.id", index=True, nullable=False)

    provider: IntegrationProvider = Field(default=IntegrationProvider.OUTLOOK, nullable=False)
    email: str = Field(max_length=320, nullable=False)
    display_name: str | None = Field(default=None, max_length=200)
    status: IntegrationStatus = Field(default=IntegrationStatus.PENDING, nullable=False)

    # Tokens OAuth (en MVP en plano; en prod van cifrados con app_secret_key)
    access_token: str | None = Field(default=None)
    refresh_token: str | None = Field(default=None)
    token_expires_at: datetime | None = Field(default=None)

    # Carpeta a vigilar (Microsoft Graph folder ID). None = inbox principal.
    watched_folder_id: str | None = Field(default=None, max_length=200)
    watched_folder_name: str | None = Field(default=None, max_length=200)

    # Polling state
    last_polled_at: datetime | None = Field(default=None)
    last_processed_message_id: str | None = Field(default=None, max_length=500)
    last_error: str | None = Field(default=None)


class EmailIntegrationRead(SQLModel):
    id: UUID
    tenant_id: UUID
    provider: IntegrationProvider
    email: str
    display_name: str | None
    status: IntegrationStatus
    watched_folder_id: str | None
    watched_folder_name: str | None
    last_polled_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
