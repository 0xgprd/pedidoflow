"""FieldMapping = regla de canonicalización per-tenant.

Mecanismo de aprendizaje incremental: el usuario corrige un campo o asigna un
concepto a un fragmento del PDF, y se persiste como regla. En la siguiente
extracción del mismo tenant, el worker aplica los mappings antes de guardar
el JSON, así que el revisor ya ve el valor canónico.

Ejemplos típicos:
    "FREIGHT COST"   → "Transporte" (FP)
    "Frais de port"  → "Transporte" (FP)
    "Shipping"       → "Transporte" (FP)

El matching es por substring case-insensitive. Si el valor del campo extraído
contiene el `source_text` del mapping, el campo entero se reemplaza por el
valor canónico (con el código entre paréntesis si lo tiene).
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin


class FieldMapping(TimestampMixin, table=True):
    """Regla canónica per-tenant."""

    __tablename__ = "field_mappings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_text_normalized",
            name="uq_field_mappings_tenant_source",
        ),
        Index("ix_field_mappings_tenant_source", "tenant_id", "source_text_normalized"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(foreign_key="tenants.id", index=True, nullable=False)

    # Texto detectado en el PDF (e.g. "FREIGHT COST"). Preservamos la forma original
    # para mostrarla al usuario; el matching va por la versión normalizada.
    source_text: str = Field(max_length=500, nullable=False)
    source_text_normalized: str = Field(max_length=500, nullable=False)

    # Concepto canónico al que se mapea (e.g. "Transporte")
    canonical_value: str = Field(max_length=500, nullable=False)
    # Código corto opcional (e.g. "FP")
    canonical_code: str | None = Field(default=None, max_length=50)

    # Glob opcional para limitar dónde aplica (e.g. "lineas.*.descripcion").
    # None = aplica a cualquier campo del JSON.
    field_path_pattern: str | None = Field(default=None, max_length=200)

    # Contador de cuántas veces se ha aplicado (analytics)
    hits: int = Field(default=0, nullable=False)


class FieldMappingRead(SQLModel):
    id: UUID
    tenant_id: UUID
    source_text: str
    canonical_value: str
    canonical_code: str | None
    field_path_pattern: str | None
    hits: int
    created_at: datetime
    updated_at: datetime


class FieldMappingCreate(SQLModel):
    source_text: str
    canonical_value: str
    canonical_code: str | None = None
    field_path_pattern: str | None = None


class FieldMappingUpdate(SQLModel):
    canonical_value: str | None = None
    canonical_code: str | None = None
    field_path_pattern: str | None = None


def normalize_source_text(text: str) -> str:
    """Normalización para matching e índices: trim + lowercase + colapsar espacios."""
    return " ".join(text.strip().lower().split())
