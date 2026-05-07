"""CatalogItem = referencia interna del tenant con precio mínimo.

El catálogo es la fuente de verdad para validar precios:
- Si una línea de pedido tiene precio < min_price → BLOQUEANTE
- Si tiene precio >= min_price → OK (aunque no haya oferta vinculada)

El catálogo se puede:
- Cargar masivamente desde CSV (POST /catalog-items/upload)
- Ir construyendo manualmente desde el form de revisión de pedidos
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin


class CatalogItem(TimestampMixin, table=True):
    """Referencia del catálogo per-tenant."""

    __tablename__ = "catalog_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "reference_normalized", name="uq_catalog_tenant_reference"),
        Index("ix_catalog_tenant_reference", "tenant_id", "reference_normalized"),
        Index("ix_catalog_tenant_active", "tenant_id", "active"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(foreign_key="tenants.id", index=True, nullable=False)

    reference: str = Field(max_length=200, nullable=False)
    # Versión normalizada (uppercase + trim) para matching case-insensitive
    reference_normalized: str = Field(max_length=200, nullable=False)

    description: str | None = Field(default=None, max_length=500)
    unit: str | None = Field(default=None, max_length=50)

    # Precios
    min_price: Decimal | None = Field(default=None, max_digits=12, decimal_places=4)
    list_price: Decimal | None = Field(default=None, max_digits=12, decimal_places=4)
    currency: str = Field(default="EUR", max_length=3, nullable=False)

    active: bool = Field(default=True, nullable=False)
    notes: str | None = Field(default=None)

    # Orden de visualización en UI. Cuando se sube un CSV (tarifa) se rellena
    # con el índice del item en el fichero (×10 para dejar hueco a inserts manuales).
    sort_order: int = Field(default=0, nullable=False)


class CatalogItemRead(SQLModel):
    id: UUID
    tenant_id: UUID
    reference: str
    description: str | None
    unit: str | None
    min_price: Decimal | None
    list_price: Decimal | None
    currency: str
    active: bool
    notes: str | None
    sort_order: int
    created_at: datetime
    updated_at: datetime


class CatalogItemCreate(SQLModel):
    reference: str
    description: str | None = None
    unit: str | None = None
    min_price: Decimal | None = None
    list_price: Decimal | None = None
    currency: str = "EUR"
    active: bool = True
    notes: str | None = None


class CatalogItemUpdate(SQLModel):
    reference: str | None = None
    description: str | None = None
    unit: str | None = None
    min_price: Decimal | None = None
    list_price: Decimal | None = None
    currency: str | None = None
    active: bool | None = None
    notes: str | None = None


def normalize_reference(ref: str) -> str:
    """Normalización para matching: uppercase + trim + colapsar espacios internos."""
    return " ".join(ref.strip().upper().split())
