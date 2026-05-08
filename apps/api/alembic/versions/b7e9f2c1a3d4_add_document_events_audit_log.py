"""add_document_events_audit_log

Revision ID: b7e9f2c1a3d4
Revises: a3f1c2e7d8b9
Create Date: 2026-05-08

Crea la tabla `document_events` para el audit log: cada acción sobre un
documento (creado, extraído, aprobado, empujado al ERP...) genera un row
inmutable con quién, qué y cuándo. Cascade delete con documents — si se
borra el doc, su historial se va con él.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b7e9f2c1a3d4"
down_revision: str | Sequence[str] | None = "a3f1c2e7d8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.document_events (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES public.tenants(id),
            document_id UUID NOT NULL REFERENCES public.documents(id) ON DELETE CASCADE,
            event_type VARCHAR(40) NOT NULL,
            actor_email VARCHAR(320),
            actor_user_id UUID,
            actor_label VARCHAR(50),
            event_data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_events_tenant_id "
        "ON public.document_events (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_events_document_id "
        "ON public.document_events (document_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_events_event_type "
        "ON public.document_events (event_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_events_created_at "
        "ON public.document_events (created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_events_document_created "
        "ON public.document_events (document_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.document_events")
