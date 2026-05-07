"""Concept = diccionario de aliases por campo del esquema.

Cada concepto agrupa N aliases (palabras del PDF) que se asocian a un campo.
- Si tiene `field_path` (ej: "cliente.nombre") → asociado a un campo del esquema.
  Cuando el worker procese un PDF, inyectará al prompt: "estos labels indican
  ese campo" para que Claude lo reconozca aunque venga en otro idioma.
- Si NO tiene `field_path` → concepto libre. Aplica como reemplazo de valor
  (substring match en cualquier campo extraído → reemplaza por name).

Scope:
- `tenant_id=NULL` → global (aplica a todos los tenants)
- `tenant_id=X` → solo aplica al tenant X

Ejemplos:
    field_path="cliente.direccion_entrega", aliases=["adresse de livraison", "shipping address"]
    field_path="pedido.numero_pedido_cliente", aliases=["numéro de commande", "PO number", "order #"]
    field_path=None, name="Transporte", code="FP", aliases=["freight cost", "frais de port"]
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin

# Lista cerrada de campos del esquema sobre los que se pueden vincular conceptos.
# Sincronizado con ExtractionResult de extraction.py.
SCHEMA_FIELDS: list[tuple[str, str, str]] = [
    # (field_path, label_humano, group)
    ("cliente.nombre", "Nombre", "Cliente"),
    ("cliente.cif_nif", "CIF / NIF", "Cliente"),
    ("cliente.numero_iva", "Nº IVA intracomunitario", "Cliente"),
    ("cliente.direccion_entrega", "Dirección de entrega", "Cliente"),
    ("cliente.direccion_facturacion", "Dirección de facturación", "Cliente"),
    ("cliente.contacto_email", "Email de contacto", "Cliente"),
    ("pedido.numero_pedido_cliente", "Nº pedido del cliente", "Pedido"),
    ("pedido.numero_oferta", "Nº oferta", "Pedido"),
    ("pedido.fecha_pedido", "Fecha del pedido", "Pedido"),
    ("pedido.fecha_entrega_solicitada", "Fecha de entrega", "Pedido"),
    ("pedido.moneda", "Moneda", "Pedido"),
    ("pedido.observaciones", "Observaciones", "Pedido"),
    ("totales.subtotal_ht", "Subtotal HT (sin IVA)", "Totales"),
    ("totales.transporte", "Transporte / Portes (€)", "Totales"),
    ("totales.iva", "IVA", "Totales"),
    ("totales.total_ttc", "Total TTC (con IVA)", "Totales"),
]
SCHEMA_FIELD_PATHS = {p for p, _, _ in SCHEMA_FIELDS}


class Concept(TimestampMixin, table=True):
    """Concepto: aliases (palabras del PDF) → campo del esquema (opcional) o valor libre."""

    __tablename__ = "concepts"
    __table_args__ = (
        Index("ix_concepts_tenant", "tenant_id"),
        Index("ix_concepts_field_path", "field_path"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # NULL = concepto global (aplica a todos los tenants)
    tenant_id: UUID | None = Field(default=None, foreign_key="tenants.id", index=True)

    name: str = Field(max_length=200, nullable=False)
    code: str | None = Field(default=None, max_length=50)

    # Si se vincula a un campo del esquema (ej: "cliente.direccion_entrega"),
    # se inyectará al prompt de Claude como pista. NULL = concepto libre (sustitución).
    field_path: str | None = Field(default=None, max_length=100)

    aliases: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False),
    )

    hits: int = Field(default=0, nullable=False)


class ConceptRead(SQLModel):
    id: UUID
    tenant_id: UUID | None
    name: str
    code: str | None
    field_path: str | None
    aliases: list[str]
    hits: int
    created_at: datetime
    updated_at: datetime


class ConceptCreate(SQLModel):
    name: str
    code: str | None = None
    field_path: str | None = None
    aliases: list[str] = Field(default_factory=list)
    is_global: bool = False


class ConceptUpdate(SQLModel):
    name: str | None = None
    code: str | None = None
    field_path: str | None = None
    aliases: list[str] | None = None
    is_global: bool | None = None


def normalize_alias(text: str) -> str:
    """Normalización para matching: trim + lowercase + colapsar espacios."""
    return " ".join(text.strip().lower().split())


def render_concept(concept: Concept) -> str:
    """Devuelve 'Name (CODE)' o solo 'Name' si no hay code."""
    if concept.code:
        return f"{concept.name} ({concept.code})"
    return concept.name
