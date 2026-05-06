"""Modelos SQLModel.

Importa aquí cada modelo para que `SQLModel.metadata` los registre.
"""

from app.models.base import TimestampMixin  # noqa: F401
from app.models.tenant import Tenant  # noqa: F401
