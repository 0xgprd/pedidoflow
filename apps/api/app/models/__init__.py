"""Modelos SQLModel.

Importa aquí cada modelo para que `SQLModel.metadata` los registre.
"""

from app.models.base import TimestampMixin  # noqa: F401
from app.models.catalog_item import CatalogItem  # noqa: F401
from app.models.document import Document, DocumentSource, DocumentStatus, DocumentType  # noqa: F401
from app.models.document_link import DocumentLink, MatchStrategy  # noqa: F401
from app.models.email_integration import (  # noqa: F401
    EmailIntegration,
    IntegrationProvider,
    IntegrationStatus,
)
from app.models.field_mapping import FieldMapping  # noqa: F401
from app.models.tenant import Tenant  # noqa: F401
from app.models.workflow_rule import RuleAction, RuleScope, WorkflowRule  # noqa: F401
