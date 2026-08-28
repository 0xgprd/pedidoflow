"""add_missing_tenant_indexes

Revision ID: bd6011526c5c
Revises: 44f0620bb842
Create Date: 2026-05-07

Sincroniza la DB con los índices declarados en los modelos SQLModel:
- Añade `ix_<table>_tenant_id` en 5 tablas — todas las queries del SaaS filtran por
  tenant, así que estos índices son críticos para rendimiento.
- Reemplaza el índice compuesto viejo `ix_documents_tenant_type` por uno simple
  `ix_documents_document_type` (filtros más comunes son por tenant solo o por type solo).
- Elimina `ix_concepts_name` (ya no útil; las búsquedas son por field_path o aliases).
"""
from collections.abc import Sequence

from alembic import op

revision: str = "bd6011526c5c"
down_revision: str | Sequence[str] | None = "44f0620bb842"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TENANT_ID_INDEXES = [
    ("ix_catalog_items_tenant_id", "catalog_items"),
    ("ix_concepts_tenant_id", "concepts"),
    ("ix_document_links_tenant_id", "document_links"),
    ("ix_email_integrations_tenant_id", "email_integrations"),
    ("ix_workflow_rules_tenant_id", "workflow_rules"),
]


def upgrade() -> None:
    for index_name, table in _TENANT_ID_INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON public.{table} (tenant_id)")
    op.execute("DROP INDEX IF EXISTS public.ix_documents_tenant_type")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_document_type "
        "ON public.documents (document_type)"
    )
    op.execute("DROP INDEX IF EXISTS public.ix_concepts_name")


def downgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_concepts_name ON public.concepts (name)")
    op.execute("DROP INDEX IF EXISTS public.ix_documents_document_type")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_tenant_type "
        "ON public.documents (tenant_id, document_type)"
    )
    for index_name, _ in _TENANT_ID_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS public.{index_name}")
