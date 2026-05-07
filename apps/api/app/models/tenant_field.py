"""TenantField = campo custom dinámico definido por el tenant.

Cada tenant puede añadir campos extra a los grupos del esquema (Cliente, Pedido,
Totales) sin tocar código. Cuando el worker procesa un PDF, inyecta estos campos
al prompt de Claude para que los extraiga al bloque `extracted_json.custom`.

Ejemplo:
    El cliente Quimilock añade un campo "Horario de entrega" en el grupo Cliente.
    field_path resultante: `custom.horario_entrega`
    Claude rellena: `extracted_json["custom"]["horario_entrega"] = "10h-13h"`

Reglas:
- `key` debe ser snake_case y único por tenant.
- `group` debe ser uno de los grupos existentes (Cliente, Pedido, Totales).
- Los aliases multi-idioma se gestionan via Concept con field_path = "custom.<key>".
"""

import re
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin

# Grupos válidos a los que se pueden añadir campos custom.
ALLOWED_GROUPS: set[str] = {"Cliente", "Pedido", "Totales"}

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,49}$")


def slugify_key(label: str) -> str:
    """Convierte un label humano a snake_case válido para usar como key.

    "Horario de entrega" → "horario_entrega"
    "Plazo (días)"      → "plazo_dias"
    """
    s = label.strip().lower()
    # Reemplazar caracteres acentuados básicos (sin librería externa)
    repl = str.maketrans("áéíóúüñàèìòùâêîôûäëïöç", "aeiouunaeiouaeiouaeoec")
    s = s.translate(repl)
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_")
    if not s:
        return ""
    if s[0].isdigit():
        s = f"f_{s}"
    return s[:50]


class TenantField(TimestampMixin, table=True):
    """Campo custom per-tenant. field_path = `custom.{key}`."""

    __tablename__ = "tenant_fields"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_tenant_fields_tenant_key"),
        Index("ix_tenant_fields_tenant", "tenant_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(foreign_key="tenants.id", nullable=False, index=True)

    group: str = Field(max_length=50, nullable=False)  # "Cliente" | "Pedido" | "Totales"
    key: str = Field(max_length=50, nullable=False)  # snake_case
    label: str = Field(max_length=200, nullable=False)
    description: str | None = Field(default=None, max_length=500)

    order: int = Field(default=0, nullable=False)

    @property
    def field_path(self) -> str:
        return f"custom.{self.key}"


class TenantFieldRead(SQLModel):
    id: UUID
    tenant_id: UUID
    group: str
    key: str
    label: str
    description: str | None
    order: int
    field_path: str
    created_at: datetime
    updated_at: datetime


class TenantFieldCreate(SQLModel):
    group: str
    label: str
    key: str | None = None  # auto-derivado del label si no se pasa
    description: str | None = None
    order: int = 0


class TenantFieldUpdate(SQLModel):
    label: str | None = None
    description: str | None = None
    order: int | None = None


def validate_key(key: str) -> bool:
    return bool(_KEY_RE.match(key))
