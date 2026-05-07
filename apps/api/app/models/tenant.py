"""Tenant = cliente del SaaS (1 empresa que usa Order Flow).

Ejemplo: Quimilock es un Tenant. Cada Tenant tendrá su propio catálogo,
sus reglas, sus credenciales Outlook+Sage, etc.
"""

from uuid import UUID, uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin


class Tenant(TimestampMixin, table=True):
    """Empresa cliente del SaaS."""

    __tablename__ = "tenants"
    __table_args__ = (
        # Nombre explícito para que coincida con el auto-name de Postgres y
        # `alembic check` no detecte drift fantasma.
        UniqueConstraint("supabase_user_id", name="tenants_supabase_user_id_key"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True, max_length=200)
    slug: str = Field(unique=True, index=True, max_length=100)
    is_active: bool = Field(default=True)
    # MVP: 1 user = 1 tenant. NULL = tenant huérfano (legacy o pendiente de claim).
    # UNIQUE declarado arriba en __table_args__ con nombre explícito.
    supabase_user_id: UUID | None = Field(
        default=None,
        index=True,
        sa_column_kwargs={
            "comment": (
                "FK a auth.users. NULL = tenant huérfano (legacy o pendiente de claim). "
                "UNIQUE = 1 user por tenant (MVP)."
            )
        },
    )


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
