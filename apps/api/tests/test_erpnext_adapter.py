"""Tests del ERPNextAdapter — usan httpx.MockTransport (sin red real).

Para tests E2E contra una instancia ERPNext real, ver test_erpnext_smoke.py
(skipped por defecto — corre solo cuando hay env vars ERPNEXT_*).
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app.services.erp.adapter import (
    AuthError,
    ERPAdapter,
    NotFoundError,
    TransientError,
    ValidationError,
)
from app.services.erp.canonical import (
    CanonicalCustomer,
    CanonicalLine,
    CanonicalSalesOrder,
)
from app.services.erp.erpnext import ERPNextAdapter, ERPNextConfig


def _config() -> ERPNextConfig:
    return ERPNextConfig(
        base_url="http://erpnext.test",
        api_key="k",
        api_secret="s",
        default_company="Quimilock Sandbox",
    )


def _make_adapter(handler) -> ERPNextAdapter:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="http://erpnext.test")
    return ERPNextAdapter(_config(), client=client)


def _quimilock_order() -> CanonicalSalesOrder:
    return CanonicalSalesOrder(
        source_document_id=uuid4(),
        customer_po_number="CF26072",
        quotation_reference="TL260420-213M1",
        customer=CanonicalCustomer(
            name="ATS",
            tax_id=None,
            eu_vat="FR76344020383",
            email="accueil@angouleme-ts.fr",
            shipping_address="Z.I. Des Agriers, 16000 Angouleme",
        ),
        order_date=date(2026, 4, 23),
        delivery_date=date(2026, 4, 30),
        currency="EUR",
        lines=[
            CanonicalLine(
                reference="T1-400",
                description="T1-400 COULEUR BLEU",
                quantity=Decimal("35"),
                unit_price=Decimal("10.9"),
                line_amount=Decimal("381.5"),
            ),
            CanonicalLine(
                reference="T-A",
                description="T-A",
                quantity=Decimal("100"),
                unit_price=Decimal("0.8"),
                line_amount=Decimal("80.0"),
            ),
        ],
        subtotal_amount=Decimal("461.5"),
        shipping_amount=Decimal("289.58"),
        total_amount=Decimal("751.08"),
        notes="Transport: FRANCO",
    )


# =============================================================================
# health_check
# =============================================================================


def test_health_check_returns_true_on_pong() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/method/ping"
        assert request.headers["authorization"] == "token k:s"
        return httpx.Response(200, json={"message": "pong"})

    assert _make_adapter(handler).health_check() is True


def test_health_check_returns_false_on_5xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "down"})

    assert _make_adapter(handler).health_check() is False


def test_health_check_returns_false_on_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    assert _make_adapter(handler).health_check() is False


# =============================================================================
# push_sales_order — happy path con creación de Customer + Items
# =============================================================================


def test_push_sales_order_creates_customer_items_and_so() -> None:
    """Caso: Customer no existe, Items no existen → adapter los crea y luego
    POST Sales Order."""
    posts: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method

        # Custom Field lookup → ya existe (no recreamos)
        if method == "GET" and path == "/api/resource/Custom Field":
            return httpx.Response(200, json={"data": [{"name": "ok"}]})

        # Customer lookup → vacío
        if method == "GET" and path == "/api/resource/Customer":
            assert "ATS" in request.url.params["filters"]
            return httpx.Response(200, json={"data": []})

        # Customer create
        if method == "POST" and path == "/api/resource/Customer":
            posts.append((path, json.loads(request.content)))
            return httpx.Response(200, json={"data": {"name": "ATS"}})

        # Item lookup → vacío
        if method == "GET" and path == "/api/resource/Item":
            return httpx.Response(200, json={"data": []})

        # Item create
        if method == "POST" and path == "/api/resource/Item":
            posts.append((path, json.loads(request.content)))
            return httpx.Response(200, json={"data": {"name": "stub"}})

        # Account lookup (cuenta de transporte)
        if method == "GET" and path == "/api/resource/Account":
            return httpx.Response(
                200,
                json={"data": [{"name": "5205 - Freight and Forwarding Charges - QS"}]},
            )

        # Sales Order create
        if method == "POST" and path == "/api/resource/Sales Order":
            posts.append((path, json.loads(request.content)))
            return httpx.Response(
                200,
                json={
                    "data": {
                        "name": "SAL-ORD-2026-00001",
                        "customer": "ATS",
                        "grand_total": 751.08,
                    }
                },
            )

        raise AssertionError(f"unexpected {method} {path}")

    adapter = _make_adapter(handler)
    result = adapter.push_sales_order(_quimilock_order())

    assert result.erp_id == "SAL-ORD-2026-00001"
    assert result.status == "draft"
    assert "/app/sales-order/SAL-ORD-2026-00001" in (result.erp_url or "")

    # Customer fue creado con eu_vat preferido sobre tax_id
    customer_post = next(p for p in posts if p[0] == "/api/resource/Customer")
    assert customer_post[1]["customer_name"] == "ATS"
    assert customer_post[1]["tax_id"] == "FR76344020383"
    assert customer_post[1]["customer_type"] == "Company"
    assert customer_post[1]["customer_group"] == "Commercial"

    # Item creates: 2 (uno por línea)
    item_posts = [p for p in posts if p[0] == "/api/resource/Item"]
    assert len(item_posts) == 2
    item_codes = {p[1]["item_code"] for p in item_posts}
    assert item_codes == {"T1-400", "T-A"}

    # Sales Order body
    so_post = next(p for p in posts if p[0] == "/api/resource/Sales Order")
    so_body = so_post[1]
    assert so_body["customer"] == "ATS"
    assert so_body["company"] == "Quimilock Sandbox"
    assert so_body["currency"] == "EUR"
    assert so_body["po_no"] == "CF26072"
    assert so_body["transaction_date"] == "2026-04-23"
    assert so_body["delivery_date"] == "2026-04-30"
    assert len(so_body["items"]) == 2
    assert so_body["items"][0]["item_code"] == "T1-400"
    assert so_body["items"][0]["qty"] == 35.0
    assert so_body["items"][0]["rate"] == 10.9
    # Transporte como charge "Actual" sobre cuenta freight (lookup por account_name)
    assert "taxes" in so_body
    assert so_body["taxes"][0]["charge_type"] == "Actual"
    assert so_body["taxes"][0]["account_head"] == "5205 - Freight and Forwarding Charges - QS"
    assert so_body["taxes"][0]["tax_amount"] == 289.58


# =============================================================================
# push_sales_order — Customer e Items ya existen (no se crean)
# =============================================================================


def test_push_sales_order_reuses_existing_customer_and_items() -> None:
    """Si Customer + Items ya existen, no se hacen POST de creación."""
    posts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method

        if method == "GET" and path == "/api/resource/Custom Field":
            return httpx.Response(200, json={"data": [{"name": "ok"}]})

        if method == "GET" and path == "/api/resource/Customer":
            return httpx.Response(200, json={"data": [{"name": "ATS"}]})

        if method == "GET" and path == "/api/resource/Item":
            # Devuelve siempre uno encontrado (independiente de qué item_code se pida)
            return httpx.Response(200, json={"data": [{"name": "found"}]})

        if method == "GET" and path == "/api/resource/Account":
            return httpx.Response(200, json={"data": [{"name": "5205 - Freight - QS"}]})

        if method == "POST" and path == "/api/resource/Sales Order":
            posts.append(path)
            return httpx.Response(200, json={"data": {"name": "SAL-ORD-X"}})

        if method == "POST":
            posts.append(path)  # nunca debería pasar
        return httpx.Response(404)

    adapter = _make_adapter(handler)
    result = adapter.push_sales_order(_quimilock_order())

    assert result.erp_id == "SAL-ORD-X"
    # Solo 1 POST: el del Sales Order. Ni Customer ni Item se recrean.
    assert posts == ["/api/resource/Sales Order"]


# =============================================================================
# push_sales_order — sin transporte, body sin "taxes"
# =============================================================================


def test_push_sales_order_raises_validation_when_freight_account_missing() -> None:
    """Si el plan contable no tiene la cuenta 'Freight and Forwarding Charges',
    el adapter levanta ValidationError clara antes de hablar con Sales Order."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path == "/api/resource/Custom Field":
            return httpx.Response(200, json={"data": [{"name": "ok"}]})
        if request.method == "GET" and path == "/api/resource/Customer":
            return httpx.Response(200, json={"data": [{"name": "ATS"}]})
        if request.method == "GET" and path == "/api/resource/Item":
            return httpx.Response(200, json={"data": [{"name": "found"}]})
        if request.method == "GET" and path == "/api/resource/Account":
            return httpx.Response(200, json={"data": []})  # ← cuenta no existe
        if request.method == "POST" and path == "/api/resource/Sales Order":
            raise AssertionError("no debería llegar a POST Sales Order")
        return httpx.Response(404)

    adapter = _make_adapter(handler)
    with pytest.raises(ValidationError, match="Freight"):
        adapter.push_sales_order(_quimilock_order())


def test_quotation_reference_creates_custom_field_first_time_and_includes_in_body() -> None:
    """Si el field no existe, el adapter lo crea (POST Custom Field) y luego
    incluye el nº de oferta en el body del Sales Order. La 2ª vez ya no se
    consulta de nuevo (cache en instancia)."""
    custom_field_creates: list[dict[str, Any]] = []
    so_body: dict[str, Any] = {}
    custom_field_get_calls = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method

        if method == "GET" and path == "/api/resource/Custom Field":
            custom_field_get_calls[0] += 1
            return httpx.Response(200, json={"data": []})  # ← no existe
        if method == "POST" and path == "/api/resource/Custom Field":
            custom_field_creates.append(json.loads(request.content))
            return httpx.Response(200, json={"data": {"name": "Sales Order-orderflow_quotation_ref"}})
        if method == "GET" and path == "/api/resource/Customer":
            return httpx.Response(200, json={"data": [{"name": "ATS"}]})
        if method == "GET" and path == "/api/resource/Item":
            return httpx.Response(200, json={"data": [{"name": "found"}]})
        if method == "GET" and path == "/api/resource/Account":
            return httpx.Response(200, json={"data": [{"name": "5205 - Freight - QS"}]})
        if method == "POST" and path == "/api/resource/Sales Order":
            so_body.update(json.loads(request.content))
            return httpx.Response(200, json={"data": {"name": "SAL-ORD-Q"}})
        return httpx.Response(404)

    adapter = _make_adapter(handler)
    adapter.push_sales_order(_quimilock_order())

    assert len(custom_field_creates) == 1
    assert custom_field_creates[0]["dt"] == "Sales Order"
    assert custom_field_creates[0]["fieldname"] == "orderflow_quotation_ref"
    assert so_body["orderflow_quotation_ref"] == "TL260420-213M1"

    # 2ª llamada: caché en instancia → no más GETs ni POSTs de Custom Field
    adapter.push_sales_order(_quimilock_order())
    assert custom_field_get_calls[0] == 1
    assert len(custom_field_creates) == 1


def test_push_sales_order_without_shipping_omits_taxes() -> None:
    captured_body: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path == "/api/resource/Custom Field":
            return httpx.Response(200, json={"data": [{"name": "ok"}]})
        if request.method == "GET" and path == "/api/resource/Customer":
            return httpx.Response(200, json={"data": [{"name": "ATS"}]})
        if request.method == "GET" and path == "/api/resource/Item":
            return httpx.Response(200, json={"data": [{"name": "found"}]})
        if request.method == "POST" and path == "/api/resource/Sales Order":
            captured_body.update(json.loads(request.content))
            return httpx.Response(200, json={"data": {"name": "SAL-ORD-Z"}})
        return httpx.Response(404)

    order = _quimilock_order().model_copy(update={"shipping_amount": None})
    _make_adapter(handler).push_sales_order(order)

    assert "taxes" not in captured_body


# =============================================================================
# Manejo de errores HTTP
# =============================================================================


def test_auth_error_on_401() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"exc_type": "AuthenticationError"})

    adapter = _make_adapter(handler)
    with pytest.raises(AuthError):
        adapter.push_sales_order(_quimilock_order())


def test_validation_error_on_417() -> None:
    """ERPNext devuelve 417 cuando rechaza el documento por reglas de negocio."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/resource/Custom Field":
            return httpx.Response(200, json={"data": [{"name": "ok"}]})
        if request.url.path == "/api/resource/Customer":
            return httpx.Response(200, json={"data": [{"name": "ATS"}]})
        if request.url.path == "/api/resource/Item":
            return httpx.Response(200, json={"data": [{"name": "found"}]})
        if request.url.path == "/api/resource/Account":
            return httpx.Response(200, json={"data": [{"name": "5205 - Freight - QS"}]})
        if request.url.path == "/api/resource/Sales Order":
            return httpx.Response(417, text="Some validation error")
        return httpx.Response(404)

    adapter = _make_adapter(handler)
    with pytest.raises(ValidationError, match="validation error"):
        adapter.push_sales_order(_quimilock_order())


def test_transient_error_on_5xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down")

    adapter = _make_adapter(handler)
    with pytest.raises(TransientError):
        adapter.push_sales_order(_quimilock_order())


def test_transient_error_on_network_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    adapter = _make_adapter(handler)
    with pytest.raises(TransientError):
        adapter.push_sales_order(_quimilock_order())


def test_not_found_error_on_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    adapter = _make_adapter(handler)
    with pytest.raises(NotFoundError):
        adapter.push_sales_order(_quimilock_order())


# =============================================================================
# Cumple Protocol
# =============================================================================


def test_erpnext_adapter_satisfies_protocol() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": "pong"})

    adapter: ERPAdapter = _make_adapter(handler)
    assert isinstance(adapter, ERPAdapter)
    assert adapter.name == "erpnext"


# =============================================================================
# Config validation
# =============================================================================


def test_config_rejects_empty_base_url() -> None:
    with pytest.raises(ValueError, match="base_url"):
        ERPNextConfig(base_url="", api_key="k", api_secret="s", default_company="C")


def test_config_rejects_missing_credentials() -> None:
    with pytest.raises(ValueError, match="api_key"):
        ERPNextConfig(base_url="http://x", api_key="", api_secret="s", default_company="C")


def test_config_rejects_empty_company() -> None:
    with pytest.raises(ValueError, match="default_company"):
        ERPNextConfig(base_url="http://x", api_key="k", api_secret="s", default_company="")


# =============================================================================
# NotImplementedError stubs
# =============================================================================


def test_push_delivery_note_not_implemented() -> None:
    adapter = _make_adapter(lambda r: httpx.Response(200, json={}))
    from app.services.erp.canonical import CanonicalDeliveryNote

    note = CanonicalDeliveryNote(
        source_document_id=uuid4(),
        customer=CanonicalCustomer(name="ACME"),
        lines=[CanonicalLine(description="x", quantity=Decimal("1"), unit_price=Decimal("1"))],
    )
    with pytest.raises(NotImplementedError):
        adapter.push_delivery_note(note)


def test_push_invoice_not_implemented() -> None:
    adapter = _make_adapter(lambda r: httpx.Response(200, json={}))
    from app.services.erp.canonical import CanonicalInvoice

    inv = CanonicalInvoice(
        source_document_id=uuid4(),
        customer=CanonicalCustomer(name="ACME"),
        lines=[CanonicalLine(description="x", quantity=Decimal("1"), unit_price=Decimal("1"))],
    )
    with pytest.raises(NotImplementedError):
        adapter.push_invoice(inv)
