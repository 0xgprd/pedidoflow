"""Tenant = cliente del SaaS (1 empresa que usa Pedidoflow).

Ejemplo: Quimilock es un Tenant. Cada Tenant tendrá su propio catálogo,
sus reglas, sus credenciales Outlook+Sage, etc.
"""

from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin


class Tenant(TimestampMixin, table=True):
    """Empresa cliente del SaaS."""

    __tablename__ = "tenants"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True, max_length=200)
    slug: str = Field(unique=True, index=True, max_length=100)
    is_active: bool = Field(default=True)


class TenantRead(SQLModel):
    """Schema público (respuesta API)."""

    id: UUID
    name: str
    slug: str
    is_active: bool


class TenantCreate(SQLModel):
    """Schema de creación."""

    name: str
    slug: str
