"""Tests del módulo ERP-neutral: modelos canónicos, mapper y contrato adapter."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from app.services.erp import (
    CanonicalCustomer,
    CanonicalLine,
    CanonicalSalesOrder,
    ERPAdapter,
    PushResult,
    extracted_to_sales_order,
)
from app.services.erp.canonical import CanonicalDeliveryNote, CanonicalInvoice


def _quimilock_extracted() -> dict[str, Any]:
    """Extracted JSON realista basado en el pedido CF26072 de Quimilock."""
    return {
        "cliente": {
            "nombre": "ATS",
            "cif_nif": "B-344020303",
            "numero_iva": "FR76344020383",
            "contacto_email": "accueil@angouleme-ts.fr",
            "direccion_entrega": "Z.I. Des Agriers, 16000 Angouleme",
            "direccion_facturacion": "Z.I. Des Agriers, 16000 Angouleme",
        },
        "pedido": {
            "numero_pedido_cliente": "CF26072",
            "numero_oferta": "TL260420-213M1",
            "fecha_pedido": "2026-04-23",
            "fecha_entrega_solicitada": "2026-04-30",
            "moneda": "EUR",
            "observaciones": "Transport: FRANCO",
        },
        "lineas": [
            {
                "referencia": "T1-400",
                "descripcion": "T1-400 COULEUR BLEU",
                "cantidad": 35,
                "unidad": None,
                "precio_unitario": 10.9,
                "importe_linea": 381.5,
            },
            {
                "referencia": "T-A",
                "descripcion": "T-A",
                "cantidad": 100,
                "precio_unitario": 0.8,
                "importe_linea": 80.0,
            },
            {
                "referencia": "TR-400",
                "descripcion": "TR-400",
                "cantidad": 20,
                "precio_unitario": 39.795,
                "importe_linea": 795.9,
            },
        ],
        "totales": {
            "subtotal_ht": 1257.4,
            "transporte": 289.58,
            "iva": None,
            "total_ttc": 1546.98,
        },
    }


# =============================================================================
# Modelos canónicos
# =============================================================================


def test_canonical_models_are_immutable() -> None:
    from pydantic import ValidationError as PydanticValidationError

    customer = CanonicalCustomer(name="ACME")
    with pytest.raises(PydanticValidationError):
        customer.name = "OTRO"  # type: ignore[misc]


def test_canonical_sales_order_minimal() -> None:
    order = CanonicalSalesOrder(
        source_document_id=uuid4(),
        customer=CanonicalCustomer(name="ACME"),
        lines=[
            CanonicalLine(
                description="Widget",
                quantity=Decimal("2"),
                unit_price=Decimal("10"),
            )
        ],
    )
    assert order.currency == "EUR"
    assert order.lines[0].tax_rate is None


def test_canonical_invoice_direction_default_sales() -> None:
    inv = CanonicalInvoice(
        source_document_id=uuid4(),
        customer=CanonicalCustomer(name="ACME"),
        lines=[
            CanonicalLine(
                description="Servicio",
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
            )
        ],
    )
    assert inv.direction == "sales"


def test_canonical_delivery_note_can_reference_order() -> None:
    note = CanonicalDeliveryNote(
        source_document_id=uuid4(),
        delivery_note_number="ALB-001",
        sales_order_reference="SO-2026-001",
        customer=CanonicalCustomer(name="ACME"),
        lines=[
            CanonicalLine(
                description="Pieza",
                quantity=Decimal("5"),
                unit_price=Decimal("12"),
            )
        ],
    )
    assert note.sales_order_reference == "SO-2026-001"


# =============================================================================
# Mapper extracted_json → CanonicalSalesOrder
# =============================================================================


def test_mapper_full_quimilock_pedido() -> None:
    doc_id = uuid4()
    extracted = _quimilock_extracted()
    order = extracted_to_sales_order(document_id=doc_id, extracted=extracted)

    assert order.source_document_id == doc_id
    assert order.customer_po_number == "CF26072"
    assert order.quotation_reference == "TL260420-213M1"
    assert order.customer.name == "ATS"
    assert order.customer.eu_vat == "FR76344020383"
    assert order.customer.shipping_address == "Z.I. Des Agriers, 16000 Angouleme"
    assert order.order_date == date(2026, 4, 23)
    assert order.delivery_date == date(2026, 4, 30)
    assert order.currency == "EUR"
    assert len(order.lines) == 3
    assert order.lines[0].reference == "T1-400"
    assert order.lines[0].quantity == Decimal("35")
    assert order.lines[0].unit_price == Decimal("10.9")
    assert order.subtotal_amount == Decimal("1257.4")
    assert order.shipping_amount == Decimal("289.58")
    assert order.total_amount == Decimal("1546.98")
    assert order.notes == "Transport: FRANCO"


def test_mapper_drops_invalid_lines() -> None:
    """Líneas con cantidad inválida o precio negativo se descartan silenciosamente."""
    extracted = _quimilock_extracted()
    extracted["lineas"].append(
        {"referencia": "BAD", "descripcion": "x", "cantidad": 0, "precio_unitario": 5}
    )
    extracted["lineas"].append(
        {"referencia": "BAD2", "descripcion": "x", "cantidad": 1, "precio_unitario": -1}
    )
    order = extracted_to_sales_order(document_id=uuid4(), extracted=extracted)
    assert len(order.lines) == 3  # las 3 originales, no las 2 malas


def test_mapper_raises_on_missing_customer_name() -> None:
    extracted = _quimilock_extracted()
    extracted["cliente"]["nombre"] = ""
    with pytest.raises(ValueError, match="Cliente sin nombre"):
        extracted_to_sales_order(document_id=uuid4(), extracted=extracted)


def test_mapper_raises_on_no_lines() -> None:
    extracted = _quimilock_extracted()
    extracted["lineas"] = []
    with pytest.raises(ValueError, match="sin líneas"):
        extracted_to_sales_order(document_id=uuid4(), extracted=extracted)


def test_mapper_raises_when_all_lines_invalid() -> None:
    extracted = _quimilock_extracted()
    extracted["lineas"] = [
        {"referencia": "X", "descripcion": "x", "cantidad": 0, "precio_unitario": 1}
    ]
    with pytest.raises(ValueError, match="líneas válidas"):
        extracted_to_sales_order(document_id=uuid4(), extracted=extracted)


def test_mapper_handles_dd_mm_yyyy_dates() -> None:
    extracted = _quimilock_extracted()
    extracted["pedido"]["fecha_pedido"] = "23/04/2026"
    extracted["pedido"]["fecha_entrega_solicitada"] = "30-04-2026"
    order = extracted_to_sales_order(document_id=uuid4(), extracted=extracted)
    assert order.order_date == date(2026, 4, 23)
    assert order.delivery_date == date(2026, 4, 30)


def test_mapper_uses_eur_default_when_currency_missing() -> None:
    extracted = _quimilock_extracted()
    extracted["pedido"]["moneda"] = None
    order = extracted_to_sales_order(document_id=uuid4(), extracted=extracted)
    assert order.currency == "EUR"


# =============================================================================
# Contrato ERPAdapter — verificable en runtime
# =============================================================================


class _FakeAdapter:
    """Implementación dummy para verificar que el Protocol se cumple."""

    name = "fake"

    def health_check(self) -> bool:
        return True

    def push_sales_order(self, order: CanonicalSalesOrder) -> PushResult:
        return PushResult(erp_id="SO-FAKE-1", erp_url=None, status="draft")

    def push_delivery_note(self, note: CanonicalDeliveryNote) -> PushResult:
        return PushResult(erp_id="DN-FAKE-1")

    def push_invoice(self, invoice: CanonicalInvoice) -> PushResult:
        return PushResult(erp_id="INV-FAKE-1")


def test_fake_adapter_satisfies_protocol() -> None:
    adapter: ERPAdapter = _FakeAdapter()
    assert isinstance(adapter, ERPAdapter)
    assert adapter.name == "fake"
    assert adapter.health_check() is True


def test_push_result_defaults() -> None:
    r = PushResult(erp_id="SO-1")
    assert r.status == "draft"
    assert r.warnings == []
    assert r.raw_response == {}
    assert r.erp_url is None
