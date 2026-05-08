"""Modelos canónicos ERP-neutral.

Order Flow extrae documentos como `Document.extracted_json` (estructura
`cliente / pedido / lineas / totales`). Para empujar al ERP necesitamos un
modelo intermedio que sea neutral respecto al ERP destino.

Diseño:
- Inmutables (`frozen=True`) — el adapter no muta canónicos.
- `Decimal` para todo dinero, nunca float.
- Campos opcionales solo donde el PDF realmente puede no tenerlos.
- Sin lógica — solo datos. El mapping desde `extracted_json` y la lógica de
  cada ERP viven en archivos separados.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CanonicalCustomer(BaseModel):
    """Cliente al que se le emite el documento."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Razón social")
    tax_id: str | None = Field(None, description="CIF/NIF/NIE local")
    eu_vat: str | None = Field(None, description="VAT intracomunitario (e.g. FRxxxxxxxxxxx)")
    email: str | None = None
    billing_address: str | None = None
    shipping_address: str | None = None


class CanonicalLine(BaseModel):
    """Línea de un pedido / albarán / factura."""

    model_config = ConfigDict(frozen=True)

    reference: str | None = Field(None, description="SKU / referencia de producto")
    description: str
    quantity: Decimal
    unit: str | None = None
    unit_price: Decimal
    line_amount: Decimal | None = Field(
        None,
        description="cantidad × precio_unitario; puede no aparecer y recalcularse en el ERP",
    )
    tax_rate: Decimal | None = Field(
        None,
        description="Tipo de IVA (e.g. 0.21 para 21%). Si None, el adapter aplica default del tenant",
    )


class CanonicalSalesOrder(BaseModel):
    """Pedido de venta — el documento que el cliente nos manda y va al ERP
    como Sales Order / Pedido de venta."""

    model_config = ConfigDict(frozen=True)

    # Trazabilidad — vincula doc del ERP con doc de Order Flow
    source_document_id: UUID = Field(..., description="documents.id de Order Flow")

    # Identificación
    customer_po_number: str | None = Field(None, description="Nº de pedido del cliente")
    quotation_reference: str | None = Field(None, description="Nº oferta vinculada")

    # Cliente
    customer: CanonicalCustomer

    # Fechas
    order_date: date | None = None
    delivery_date: date | None = None

    # Líneas + moneda
    currency: str = Field("EUR", description="ISO 4217")
    lines: list[CanonicalLine]

    # Totales declarados — el adapter normalmente recalcula y compara
    subtotal_amount: Decimal | None = None
    shipping_amount: Decimal | None = None
    tax_amount: Decimal | None = None
    total_amount: Decimal | None = None

    notes: str | None = None


class CanonicalDeliveryNote(BaseModel):
    """Albarán — documento de envío. Puede referenciar al pedido del que viene."""

    model_config = ConfigDict(frozen=True)

    source_document_id: UUID
    delivery_note_number: str | None = Field(None, description="Nº albarán emitido por el cliente")
    sales_order_reference: str | None = Field(None, description="Nº pedido al que pertenece")

    customer: CanonicalCustomer
    delivery_date: date | None = None

    lines: list[CanonicalLine]
    notes: str | None = None


class CanonicalInvoice(BaseModel):
    """Factura — emitida o recibida (`direction`)."""

    model_config = ConfigDict(frozen=True)

    source_document_id: UUID
    invoice_number: str | None = None
    sales_order_reference: str | None = None
    delivery_note_reference: str | None = None

    direction: Literal["sales", "purchase"] = "sales"
    customer: CanonicalCustomer

    invoice_date: date | None = None
    due_date: date | None = None

    currency: str = "EUR"
    lines: list[CanonicalLine]

    subtotal_amount: Decimal | None = None
    tax_amount: Decimal | None = None
    total_amount: Decimal | None = None

    notes: str | None = None
