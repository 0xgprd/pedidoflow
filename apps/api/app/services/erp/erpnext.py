"""ERPNext adapter (open source / self-hosted).

Habla con un site ERPNext via REST API. Crea Customer e Item si no existen,
luego empuja Sales Order. Por defecto el documento queda en estado `Draft`
(`docstatus=0`) — el usuario lo confirma manualmente desde la UI del ERP.

Doc oficial:
- https://docs.frappe.io/framework/user/en/api/rest
- https://docs.frappe.io/erpnext/user/manual/en/sales-order

Autenticación: header `Authorization: token <api_key>:<api_secret>`. Generar
las claves desde Frappe `bench --site <site> execute frappe.core.doctype.user.user.generate_keys --args "['Administrator']"`.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import httpx

from app.core.logging import get_logger
from app.services.erp.adapter import (
    AuthError,
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

log = get_logger(__name__)


class ERPNextConfig:
    """Configuración del adapter (no Pydantic — evita ciclo con app.core.config)."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        api_secret: str,
        default_company: str,
        default_currency: str = "EUR",
        default_customer_group: str = "Commercial",
        default_territory: str = "Spain",
        default_item_group: str = "All Item Groups",
        default_stock_uom: str = "Nos",
        timeout_seconds: float = 30.0,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not api_key or not api_secret:
            raise ValueError("api_key and api_secret are required")
        if not default_company:
            raise ValueError("default_company is required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.default_company = default_company
        self.default_currency = default_currency
        self.default_customer_group = default_customer_group
        self.default_territory = default_territory
        self.default_item_group = default_item_group
        self.default_stock_uom = default_stock_uom
        self.timeout_seconds = timeout_seconds


class ERPNextAdapter:
    """Implementación de `ERPAdapter` para ERPNext."""

    name = "erpnext"

    def __init__(
        self,
        config: ERPNextConfig,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=config.base_url,
            timeout=config.timeout_seconds,
        )
        # Aplicamos auth header siempre (incluso si nos pasaron client externo,
        # para no depender de cómo lo configuraron).
        self._client.headers["Authorization"] = f"token {config.api_key}:{config.api_secret}"
        self._client.headers["Accept"] = "application/json"

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # =========================================================================
    # Public API (ERPAdapter Protocol)
    # =========================================================================

    def health_check(self) -> bool:
        try:
            r = self._client.get("/api/method/ping")
            return r.status_code == 200 and r.json().get("message") == "pong"
        except (httpx.HTTPError, ValueError):
            return False

    def push_sales_order(self, order: CanonicalSalesOrder) -> PushResult:
        log.info(
            "erpnext.push_sales_order.start",
            customer_po=order.customer_po_number,
            customer=order.customer.name,
            lines=len(order.lines),
        )

        # 0. Custom field "Quotation Reference" en Sales Order — solo se crea
        # la primera vez que se necesita (idempotente).
        if order.quotation_reference:
            self._ensure_quotation_ref_field()

        # 1. Cliente: crear si no existe
        customer_name = self._ensure_customer(order.customer)

        # 2. Items: crear si no existen
        for line in order.lines:
            self._ensure_item(line)

        # 3. POST Sales Order
        body = self._build_sales_order_body(order, customer_name)
        r = self._post("/api/resource/Sales Order", body)
        data = r.json()["data"]

        warnings: list[str] = []
        # Si recibimos `_server_messages` con avisos no fatales, los exponemos
        msgs = data.get("_server_messages")
        if msgs:
            try:
                parsed = json.loads(msgs)
                warnings = [str(m) for m in parsed if m]
            except (ValueError, TypeError):
                warnings = [str(msgs)]

        log.info(
            "erpnext.push_sales_order.ok",
            erp_id=data["name"],
            customer=customer_name,
        )

        return PushResult(
            erp_id=data["name"],
            erp_url=f"{self.config.base_url}/app/sales-order/{quote(data['name'])}",
            status="draft",
            warnings=warnings,
            raw_response=data,
        )

    def push_delivery_note(self, note: CanonicalDeliveryNote) -> PushResult:
        raise NotImplementedError(
            "push_delivery_note pendiente — se implementa cuando Order Flow extraiga albaranes",
        )

    def push_invoice(self, invoice: CanonicalInvoice) -> PushResult:
        raise NotImplementedError(
            "push_invoice pendiente — se implementa cuando Order Flow extraiga facturas",
        )

    # =========================================================================
    # Customer / Item bootstrap
    # =========================================================================

    def _ensure_customer(self, customer: CanonicalCustomer) -> str:
        """Devuelve el `name` (PK) del Customer en ERPNext, creándolo si no existe.

        Lookup por `customer_name` (case-sensitive). Esto evita duplicados cuando
        el mismo cliente aparece en varios pedidos.
        """
        existing = self._get_list("Customer", filters=[["customer_name", "=", customer.name]])
        if existing:
            return existing[0]["name"]

        body: dict[str, Any] = {
            "customer_name": customer.name,
            "customer_type": "Company",
            "customer_group": self.config.default_customer_group,
            "territory": self.config.default_territory,
        }
        # Tax ID: preferimos eu_vat (intracom) si existe, sino tax_id local
        if customer.eu_vat:
            body["tax_id"] = customer.eu_vat
        elif customer.tax_id:
            body["tax_id"] = customer.tax_id
        if customer.email:
            body["email_id"] = customer.email

        r = self._post("/api/resource/Customer", body)
        return r.json()["data"]["name"]

    def _ensure_item(self, line: CanonicalLine) -> str:
        """Garantiza que el Item existe; si no, crea uno minimal (no-stock)."""
        item_code = self._derive_item_code(line)
        existing = self._get_list("Item", filters=[["item_code", "=", item_code]])
        if existing:
            return item_code

        body: dict[str, Any] = {
            "item_code": item_code,
            "item_name": (line.description or item_code)[:140],
            "item_group": self.config.default_item_group,
            "stock_uom": line.unit or self.config.default_stock_uom,
            # No-stock: Order Flow no controla inventario; solo empuja precios y refs
            "is_stock_item": 0,
        }
        self._post("/api/resource/Item", body)
        return item_code

    @staticmethod
    def _derive_item_code(line: CanonicalLine) -> str:
        """item_code es la clave única en ERPNext. Si el PDF trajo `referencia` la
        usamos; si no, derivamos de la descripción truncada."""
        if line.reference:
            return line.reference.strip()[:140]
        if line.description:
            return line.description.strip()[:140]
        return "UNCATALOGED-ITEM"

    # =========================================================================
    # Body building
    # =========================================================================

    # Nombre del custom field que añadimos a Sales Order para guardar el nº de
    # oferta original que extrajo Order Flow del PDF (vínculo con la oferta de
    # comercial). Prefijo `orderflow_` para no chocar con campos nativos.
    _QUOTATION_REF_FIELDNAME = "orderflow_quotation_ref"

    def _ensure_quotation_ref_field(self) -> None:
        """Crea el Custom Field 'Quotation Reference' en Sales Order si no existe.

        Idempotente: lookup primero, sólo crea si falta. Se llama una vez por
        instancia ERPNext (la primera vez que un pedido lleva nº de oferta).
        """
        if getattr(self, "_quotation_field_ensured", False):
            return
        existing = self._get_list(
            "Custom Field",
            filters=[
                ["dt", "=", "Sales Order"],
                ["fieldname", "=", self._QUOTATION_REF_FIELDNAME],
            ],
        )
        if not existing:
            self._post(
                "/api/resource/Custom Field",
                {
                    "dt": "Sales Order",
                    "fieldname": self._QUOTATION_REF_FIELDNAME,
                    "label": "Quotation Reference (Order Flow)",
                    "fieldtype": "Data",
                    "insert_after": "po_no",
                    "description": (
                        "Nº de oferta original extraído por Order Flow del PDF "
                        "del cliente. Sirve de trazabilidad oferta↔pedido."
                    ),
                },
            )
            log.info("erpnext.custom_field.created", fieldname=self._QUOTATION_REF_FIELDNAME)
        self._quotation_field_ensured = True

    def _build_sales_order_body(
        self, order: CanonicalSalesOrder, customer_name: str
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for line in order.lines:
            row: dict[str, Any] = {
                "item_code": self._derive_item_code(line),
                "item_name": (line.description or self._derive_item_code(line))[:140],
                "qty": float(line.quantity),
                "rate": float(line.unit_price),
            }
            if line.unit:
                row["uom"] = line.unit
            if order.delivery_date:
                row["delivery_date"] = order.delivery_date.isoformat()
            items.append(row)

        body: dict[str, Any] = {
            "customer": customer_name,
            "company": self.config.default_company,
            "currency": order.currency,
            "items": items,
        }
        if order.order_date:
            body["transaction_date"] = order.order_date.isoformat()
        if order.delivery_date:
            body["delivery_date"] = order.delivery_date.isoformat()
        if order.customer_po_number:
            body["po_no"] = order.customer_po_number
        if order.quotation_reference:
            body[self._QUOTATION_REF_FIELDNAME] = order.quotation_reference
        if order.notes:
            body["terms"] = order.notes

        # Transporte como charge actual sobre la cuenta "Freight and Forwarding".
        # Si la cuenta no existe en el plan contable, ERPNext devolverá ValidationError
        # y nuestro adapter lo propagará como excepción tipada — el caller decide.
        if order.shipping_amount and order.shipping_amount > 0:
            body["taxes"] = [
                {
                    "charge_type": "Actual",
                    "account_head": self._freight_account_head(),
                    "description": "Transporte",
                    "tax_amount": float(order.shipping_amount),
                }
            ]
        return body

    def _freight_account_head(self) -> str:
        """Cuenta de Freight & Forwarding del plan contable de la empresa.

        El nombre concreto varía por país y plan contable elegido:
        - Plan ERPNext numerado: `5205 - Freight and Forwarding Charges - <ABBR>`
        - Otros planes: el prefijo numérico cambia o no existe.

        Hacemos lookup por `account_name` para no asumir el número. Cacheamos
        el resultado para no consultar en cada push.
        """
        if hasattr(self, "_freight_account_cache"):
            return self._freight_account_cache  # type: ignore[no-any-return]

        accounts = self._get_list(
            "Account",
            filters=[
                ["company", "=", self.config.default_company],
                ["account_name", "=", "Freight and Forwarding Charges"],
            ],
            fields=["name"],
        )
        if not accounts:
            raise ValidationError(
                "No existe cuenta 'Freight and Forwarding Charges' en el plan contable de "
                f"'{self.config.default_company}'. Crea la cuenta o desactiva el push de "
                "transporte.",
            )
        self._freight_account_cache: str = accounts[0]["name"]
        return self._freight_account_cache

    # =========================================================================
    # HTTP helpers
    # =========================================================================

    def _get_list(
        self, doctype: str, filters: list[list[str]], fields: list[str] | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "filters": json.dumps(filters),
            "limit_page_length": 1,
        }
        if fields:
            params["fields"] = json.dumps(fields)
        r = self._get(f"/api/resource/{quote(doctype)}", params=params)
        return r.json().get("data", [])

    def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        try:
            r = self._client.get(path, params=params)
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            raise TransientError(f"network error calling GET {path}: {e}") from e
        self._raise_on_error(r, path)
        return r

    def _post(self, path: str, body: dict[str, Any]) -> httpx.Response:
        try:
            r = self._client.post(path, json=body)
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            raise TransientError(f"network error calling POST {path}: {e}") from e
        self._raise_on_error(r, path)
        return r

    @staticmethod
    def _raise_on_error(r: httpx.Response, path: str) -> None:
        if 200 <= r.status_code < 300:
            return
        body_excerpt = r.text[:1000]
        if r.status_code in (401, 403):
            raise AuthError(f"{r.status_code} on {path}: {body_excerpt}")
        if r.status_code == 404:
            raise NotFoundError(f"404 on {path}: {body_excerpt}")
        if r.status_code in (400, 409, 417, 422):
            raise ValidationError(f"{r.status_code} on {path}: {body_excerpt}")
        if 500 <= r.status_code < 600:
            raise TransientError(f"{r.status_code} on {path}: {body_excerpt}")
        raise ValidationError(f"unexpected {r.status_code} on {path}: {body_excerpt}")
