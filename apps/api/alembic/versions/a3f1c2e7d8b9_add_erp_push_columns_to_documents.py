"""add_erp_push_columns_to_documents

Revision ID: a3f1c2e7d8b9
Revises: bd6011526c5c
Create Date: 2026-05-08

Añade columnas para trazar push a ERP en `documents`:
- `erp_adapter`   identificador del adapter usado (e.g. "erpnext")
- `erp_id`        ID del documento creado en el ERP destino
- `erp_url`       URL al documento en la UI del ERP
- `erp_pushed_at` cuándo se empujó por última vez
- `erp_push_error` último error si el push falló (None tras éxito)
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a3f1c2e7d8b9"
down_revision: str | Sequence[str] | None = "bd6011526c5c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.documents
            ADD COLUMN IF NOT EXISTS erp_adapter VARCHAR(50),
            ADD COLUMN IF NOT EXISTS erp_id VARCHAR(200),
            ADD COLUMN IF NOT EXISTS erp_url VARCHAR(500),
            ADD COLUMN IF NOT EXISTS erp_pushed_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS erp_push_error TEXT
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.documents
            DROP COLUMN IF EXISTS erp_push_error,
            DROP COLUMN IF EXISTS erp_pushed_at,
            DROP COLUMN IF EXISTS erp_url,
            DROP COLUMN IF EXISTS erp_id,
            DROP COLUMN IF EXISTS erp_adapter
        """
    )
