"""Capa ERP-neutral.

Order Flow habla con cualquier ERP a través de:

1. **Modelos canónicos** (`canonical.py`) — neutral respecto al ERP destino.
2. **Interfaz `ERPAdapter`** (`adapter.py`) — contrato que cada ERP cumple.
3. **Mapper** (`mapping.py`) — traduce `Document.extracted_json` a canónico.

Implementaciones concretas:
- `erpnext.ERPNextAdapter` — primer ERP soportado (open source, sandbox).
- otros adapters (Sage 200, Holded, CSV export) llegan en futuras iteraciones.
"""

from app.services.erp.adapter import (
    AuthError,
    CustomerNotRegisteredError,
    ERPAdapter,
    ERPAdapterError,
    NotFoundError,
    PushResult,
    TransientError,
    ValidationError,
)
from app.services.erp.canonical import (
    CanonicalCustomer,
    CanonicalDeliveryNote,
    CanonicalInvoice,
    CanonicalLine,
    CanonicalSalesOrder,
)
from app.services.erp.factory import get_erp_adapter
from app.services.erp.mapping import extracted_to_sales_order

__all__ = [
    "AuthError",
    "CanonicalCustomer",
    "CanonicalDeliveryNote",
    "CanonicalInvoice",
    "CanonicalLine",
    "CanonicalSalesOrder",
    "CustomerNotRegisteredError",
    "ERPAdapter",
    "ERPAdapterError",
    "NotFoundError",
    "PushResult",
    "TransientError",
    "ValidationError",
    "extracted_to_sales_order",
    "get_erp_adapter",
]
