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
    CanonicalCustomerRegistration,
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


class CustomerRegistrationResult(BaseModel):
    """Resultado de dar de alta un cliente en el ERP."""

    erp_customer_id: str = Field(..., description="Nombre/ID del Customer creado")
    erp_customer_url: str | None = None
    addresses_created: int = 0
    contacts_created: int = 0
    warnings: list[str] = Field(default_factory=list)
    raw_response: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Errores
# =============================================================================


class ERPAdapterError(Exception):
    """Error genérico al hablar con un ERP."""


class AuthError(ERPAdapterError):
    """Credenciales inválidas o caducadas."""


class NotFoundError(ERPAdapterError):
    """Recurso referenciado no existe en el ERP."""


class CustomerNotRegisteredError(NotFoundError):
    """El cliente referenciado en el documento no está dado de alta en el ERP.

    Subclase específica de NotFoundError porque el flujo de remediación es
    distinto: no es un error técnico, es un estado de negocio normal — hay
    que dar de alta al cliente primero (con una ficha de alta).
    """

    def __init__(self, *, customer_name: str, lookup_hints: list[str]) -> None:
        self.customer_name = customer_name
        self.lookup_hints = lookup_hints
        super().__init__(
            f"Cliente '{customer_name}' no está dado de alta en el ERP. "
            f"Búsqueda intentada por: {', '.join(lookup_hints)}."
        )


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

    def register_customer(
        self, registration: CanonicalCustomerRegistration
    ) -> CustomerRegistrationResult:
        """Da de alta un cliente en el ERP a partir de los datos extraídos
        de una ficha de alta. Crea Customer + Addresses + Contacts en una
        sola operación."""
        ...
