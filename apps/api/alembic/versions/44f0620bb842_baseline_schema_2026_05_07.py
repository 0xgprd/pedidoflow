"""baseline_schema_2026_05_07

Revision ID: 44f0620bb842
Revises:
Create Date: 2026-05-07

Baseline vacía: el schema actual (tenants, documents, document_links, concepts,
tenant_fields, catalog_items, email_integrations, workflow_rules) ya estaba
creado por `init_db().create_all()` antes de adoptar Alembic.

Para DBs nuevas que arranquen desde cero con Alembic, esta migración no crea
nada — confiamos en `init_db()` para el bootstrap inicial. A partir de la siguiente
revisión las migraciones SÍ contienen DDL real.

Para DBs existentes (Quimilock, Supabase prod), `alembic stamp head` marca esta
revisión como aplicada sin tocar nada.
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "44f0620bb842"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: schema preexistente."""
    pass


def downgrade() -> None:
    """No-op: la baseline no se puede revertir."""
    pass
