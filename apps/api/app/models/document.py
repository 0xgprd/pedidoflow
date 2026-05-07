"""Document = pedido recibido (PDF) que entra al pipeline de extracción.

Lifecycle:
    pending     → recién creado, esperando worker
    processing  → worker lo está extrayendo
    extracted   → IA devolvió JSON estructurado, esperando revisión humana
    failed      → error técnico (ver extraction_error)
    approved    → revisado y validado por humano (listo para Sage)
    rejected    → rechazado por humano (no procesar)
"""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin


class DocumentSource(StrEnum):
    UPLOAD = "upload"
    EMAIL = "email"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    EXTRACTED = "extracted"
    FAILED = "failed"
    APPROVED = "approved"
    REJECTED = "rejected"


class DocumentType(StrEnum):
    PEDIDO = "pedido"
    OFERTA = "oferta"
    DESCONOCIDO = "desconocido"


class Document(TimestampMixin, table=True):
    """PDF de pedido + resultado de la extracción IA."""

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_tenant_status_created", "tenant_id", "status", "created_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(foreign_key="tenants.id", index=True, nullable=False)

    source: DocumentSource = Field(default=DocumentSource.UPLOAD, nullable=False)
    status: DocumentStatus = Field(default=DocumentStatus.PENDING, nullable=False, index=True)
    # NOTA: la columna en Postgres es VARCHAR (no enum nativo) para evitar el
    # mapping por NAME (uppercase) por defecto de SQLAlchemy. La columna se
    # creó con `ALTER TABLE` manual.
    document_type: DocumentType = Field(
        default=DocumentType.DESCONOCIDO,
        sa_column=Column(String(20), nullable=False, server_default="desconocido", index=True),
    )

    pdf_key: str = Field(max_length=500, nullable=False)
    original_filename: str | None = Field(default=None, max_length=500)
    source_email: str | None = Field(default=None, max_length=320)

    raw_text: str | None = Field(default=None)
    ocr_result: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON().with_variant(JSONB(), "postgresql")),
    )
    extracted_json: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON().with_variant(JSONB(), "postgresql")),
    )
    extraction_error: str | None = Field(default=None)

    processed_at: datetime | None = Field(default=None)
    # Fecha real de recepción del email (cuando source=email). None para uploads manuales.
    email_received_at: datetime | None = Field(default=None, index=True)
    # Flags pre-calculados para que la bandeja no tenga que cargar extracted_json:
    # - True si validation tiene blockings o workflow.blocked
    has_blocking_issues: bool = Field(default=False, nullable=False, index=True)
    # - True si tiene oferta vinculada con discrepancias
    has_discrepancies: bool = Field(default=False, nullable=False, index=True)


class DocumentRead(SQLModel):
    """Schema completo (incluye extracted_json + raw_text). Usar en GET por ID."""

    id: UUID
    tenant_id: UUID
    source: DocumentSource
    status: DocumentStatus
    document_type: DocumentType
    pdf_key: str
    original_filename: str | None
    source_email: str | None
    extracted_json: dict[str, Any] | None
    extraction_error: str | None
    has_blocking_issues: bool
    has_discrepancies: bool
    created_at: datetime
    updated_at: datetime
    processed_at: datetime | None
    email_received_at: datetime | None


class DocumentListItem(SQLModel):
    """Schema ligero para listas — sin extracted_json/ocr_result (10-50× menos payload).

    Incluye flags pre-calculados para que la bandeja muestre iconos de aviso sin
    cargar el JSON entero:
    - `has_blocking_issues`: validation con blockings o workflow.blocked
    - `has_discrepancies`: pedido vinculado a oferta con diferencias precio/cantidad
    - `has_offer_link`: pedido tiene oferta vinculada (None para no-pedidos).
      Se calcula on-the-fly en `list_documents` (no es columna de DB).
    """

    id: UUID
    tenant_id: UUID
    source: DocumentSource
    status: DocumentStatus
    document_type: DocumentType
    original_filename: str | None
    source_email: str | None
    extraction_error: str | None
    has_blocking_issues: bool
    has_discrepancies: bool
    has_offer_link: bool | None = None
    created_at: datetime
    updated_at: datetime
    processed_at: datetime | None
    email_received_at: datetime | None


class DocumentCreate(SQLModel):
    """Crear un Document directamente (uso interno / tests).

    El flujo normal va por `POST /documents` que recibe `UploadFile`.
    """

    source: DocumentSource = DocumentSource.UPLOAD
    pdf_key: str
    original_filename: str | None = None
    source_email: str | None = None


class DocumentUpdate(SQLModel):
    """Actualización parcial — usado por worker y por revisión humana."""

    status: DocumentStatus | None = None
    raw_text: str | None = None
    extracted_json: dict[str, Any] | None = None
    extraction_error: str | None = None
    processed_at: datetime | None = None
