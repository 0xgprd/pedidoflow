"""Mapper de `Document.extracted_json` → modelos canónicos.

Order Flow guarda los documentos extraídos con estructura
`cliente / pedido / lineas / totales`. Cuando el usuario aprueba un pedido,
esta función traduce esa estructura al modelo canónico que el adapter del
ERP entiende.

Por ahora solo está implementado `extracted_to_sales_order` (pedido). Albarán
y factura se añadirán cuando esos tipos de documento entren al pipeline.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from app.services.erp.canonical import (
    CanonicalCustomer,
    CanonicalLine,
    CanonicalSalesOrder,
)


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    return None


def extracted_to_sales_order(
    *,
    document_id: UUID,
    extracted: dict[str, Any],
) -> CanonicalSalesOrder:
    """Traduce un `extracted_json` de pedido a `CanonicalSalesOrder`.

    Lanza `ValueError` si faltan campos esenciales (cliente.nombre o sin líneas
    válidas). Los campos opcionales se pasan como None — el adapter del ERP
    decide cómo rellenar (defaults del tenant).
    """
    cliente_raw = extracted.get("cliente") or {}
    pedido_raw = extracted.get("pedido") or {}
    totales_raw = extracted.get("totales") or {}
    lineas_raw = extracted.get("lineas") or []

    nombre = cliente_raw.get("nombre")
    if not nombre or not str(nombre).strip():
        raise ValueError("Cliente sin nombre — no se puede mapear a Sales Order")

    if not lineas_raw:
        raise ValueError("Pedido sin líneas — no se puede mapear a Sales Order")

    customer = CanonicalCustomer(
        name=str(nombre).strip(),
        tax_id=cliente_raw.get("cif_nif"),
        eu_vat=cliente_raw.get("numero_iva"),
        email=cliente_raw.get("contacto_email"),
        billing_address=cliente_raw.get("direccion_facturacion"),
        shipping_address=cliente_raw.get("direccion_entrega"),
    )

    lines: list[CanonicalLine] = []
    for raw in lineas_raw:
        qty = _decimal(raw.get("cantidad"))
        unit_price = _decimal(raw.get("precio_unitario"))
        # Necesitamos al menos cantidad y precio para tener una línea válida
        if qty is None or qty <= 0 or unit_price is None or unit_price < 0:
            continue
        lines.append(
            CanonicalLine(
                reference=raw.get("referencia"),
                description=str(raw.get("descripcion") or "").strip(),
                quantity=qty,
                unit=raw.get("unidad"),
                unit_price=unit_price,
                line_amount=_decimal(raw.get("importe_linea")),
                tax_rate=None,  # adapter aplicará default del tenant
            )
        )

    if not lines:
        raise ValueError("Pedido sin líneas válidas tras normalizar")

    return CanonicalSalesOrder(
        source_document_id=document_id,
        customer_po_number=pedido_raw.get("numero_pedido_cliente"),
        quotation_reference=pedido_raw.get("numero_oferta"),
        customer=customer,
        order_date=_parse_date(pedido_raw.get("fecha_pedido")),
        delivery_date=_parse_date(pedido_raw.get("fecha_entrega_solicitada")),
        currency=str(pedido_raw.get("moneda") or "EUR"),
        lines=lines,
        subtotal_amount=_decimal(totales_raw.get("subtotal_ht")),
        shipping_amount=_decimal(totales_raw.get("transporte")),
        tax_amount=_decimal(totales_raw.get("iva")),
        total_amount=_decimal(totales_raw.get("total_ttc")),
        notes=pedido_raw.get("observaciones"),
    )
