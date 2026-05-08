"""Interfaz `ERPAdapter` y resultado común.

Cada ERP soportado implementa este Protocol. La capa de servicio
(flujo de aprobación de documentos) habla SOLO con esta interfaz, así
añadir un ERP nuevo es escribir un adapter sin tocar el resto.

El adapter recibe modelos canónicos (`canonical.py`), no `extracted_json`
ni modelos SQLAlchemy. Esto mantiene la frontera limpia.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from app.services.erp.canonical import (
    CanonicalDeliveryNote,
    CanonicalInvoice,
    CanonicalSalesOrder,
)


class PushResult(BaseModel):
    """Resultado de empujar un documento canónico al ERP."""

    erp_id: str = Field(..., description="ID del documento en el ERP (e.g. SO-2026-0001)")
    erp_url: str | None = Field(None, description="URL para ver/editar el doc en la UI del ERP")
    status: Literal["draft", "submitted", "cancelled"] = "draft"
    warnings: list[str] = Field(default_factory=list)
    raw_response: dict[str, Any] = Field(
        default_factory=dict, description="Respuesta cruda del ERP (debug)"
    )


# =============================================================================
# Errores
# =============================================================================


class ERPAdapterError(Exception):
    """Error genérico al hablar con un ERP."""


class AuthError(ERPAdapterError):
    """Credenciales inválidas o caducadas."""


class NotFoundError(ERPAdapterError):
    """Cliente o producto referenciado no existe en el ERP."""


class ValidationError(ERPAdapterError):
    """El ERP rechazó el documento por reglas de negocio (IVA mal, total no cuadra...)."""


class TransientError(ERPAdapterError):
    """Timeout / 5xx / red — reintentable."""


# =============================================================================
# Protocol
# =============================================================================


@runtime_checkable
class ERPAdapter(Protocol):
    """Contrato que cada ERP implementa.

    Implementaciones previstas:
    - `app.services.erp.erpnext.ERPNextAdapter`
    - `app.services.erp.csv_export.CSVExportAdapter` (futuro)
    - `app.services.erp.sage200.Sage200Adapter` (futuro)
    - `app.services.erp.holded.HoldedAdapter` (futuro)
    """

    name: str  # identificador estable, e.g. "erpnext"

    def health_check(self) -> bool:
        """True si el ERP está accesible con las credenciales actuales."""
        ...

    def push_sales_order(self, order: CanonicalSalesOrder) -> PushResult:
        """Crea un Sales Order en el ERP. Status `draft` por defecto."""
        ...

    def push_delivery_note(self, note: CanonicalDeliveryNote) -> PushResult:
        """Crea un Delivery Note (albarán) en el ERP."""
        ...

    def push_invoice(self, invoice: CanonicalInvoice) -> PushResult:
        """Crea una Sales o Purchase Invoice en el ERP."""
        ...
