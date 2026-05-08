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
    CustomerNotRegisteredError,
    CustomerRegistrationResult,
    NotFoundError,
    PushResult,
    TransientError,
    ValidationError,
)
from app.services.erp.canonical import (
    CanonicalAddress,
    CanonicalContact,
    CanonicalCustomer,
    CanonicalCustomerRegistration,
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

        # 1. Cliente: BUSCAR si existe. NO crear desde un pedido — los clientes
        # se dan de alta con una ficha específica (ver `register_customer`).
        # Si el cliente no existe, lanzamos CustomerNotRegisteredError y el
        # caller (endpoint) responde al usuario con instrucciones para subir
        # la ficha de alta.
        customer_name = self._lookup_customer_or_fail(order.customer)

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
    # Alta de cliente — Customer + Addresses + Contacts en una operación
    # =========================================================================

    def register_customer(
        self, registration: CanonicalCustomerRegistration
    ) -> CustomerRegistrationResult:
        """Da de alta un cliente nuevo en ERPNext con TODOS sus datos.

        Crea (en este orden):
            1. Customer (con tax_category, payment_terms_template, idioma...)
            2. Address fiscal (vinculada via Dynamic Link)
            3. Address de facturación si distinta
            4. Address de envío si distinta
            5. Contact por cada persona en `registration.contacts`
            6. Custom Fields para supplier_number_in_customer_system y
               signed_by_* — auto-creados la primera vez.

        Si el cliente YA existe (mismo customer_name), levanta ValidationError
        — el caller debería detectar esto antes para evitarlo.
        """
        log.info(
            "erpnext.register_customer.start",
            company=registration.company_name,
            tax_category=registration.tax_category,
        )

        # Asegurar custom fields auxiliares
        self._ensure_supplier_number_field()
        if registration.signed_by_name or registration.signature_date:
            self._ensure_signature_fields()

        warnings: list[str] = []

        # 0. Asegurar que Territory y Tax Category referenciados EXISTEN como
        # Doctype en ERPNext. Si no, los creamos. El setup wizard solo crea
        # algunos territories básicos — clientes franceses, alemanes etc.
        # fallarían sin esto.
        territory_to_use = registration.fiscal_address.country or self.config.default_territory
        if territory_to_use:
            try:
                self._ensure_territory(territory_to_use)
            except (ValidationError, NotFoundError) as e:
                warnings.append(f"Territory '{territory_to_use}' no se pudo crear: {e}")
                territory_to_use = self.config.default_territory

        tax_label = self._TAX_CATEGORY_LABELS.get(registration.tax_category, "")
        tax_category_ok = False
        if tax_label:
            try:
                self._ensure_tax_category(tax_label)
                tax_category_ok = True
            except (ValidationError, NotFoundError) as e:
                warnings.append(
                    f"Tax Category '{tax_label}' no se pudo crear — "
                    f"se omite del cliente (puedes asignarla a mano en el ERP): {e}"
                )

        # 1. Crear Customer
        customer_body = self._build_customer_body(
            registration,
            territory_override=territory_to_use,
            include_tax_category=tax_category_ok,
        )
        try:
            r = self._post("/api/resource/Customer", customer_body)
        except ValidationError as e:
            # Si ERPNext rechaza por duplicado, lo propagamos con mensaje claro
            raise ValidationError(
                f"No se pudo crear el cliente en ERPNext (¿duplicado?): {e}"
            ) from e
        customer_name = r.json()["data"]["name"]

        # 2-4. Crear addresses
        addresses_created = 0
        try:
            self._create_address(
                customer_name, registration.fiscal_address, address_type="Permanent"
            )
            addresses_created += 1
        except (ValidationError, NotFoundError) as e:
            warnings.append(f"No se pudo crear address fiscal: {e}")

        if (
            registration.billing_address
            and registration.billing_address != registration.fiscal_address
        ):
            try:
                self._create_address(
                    customer_name, registration.billing_address, address_type="Billing"
                )
                addresses_created += 1
            except (ValidationError, NotFoundError) as e:
                warnings.append(f"No se pudo crear address facturación: {e}")

        if (
            registration.shipping_address
            and registration.shipping_address != registration.fiscal_address
            and registration.shipping_address != registration.billing_address
        ):
            try:
                self._create_address(
                    customer_name, registration.shipping_address, address_type="Shipping"
                )
                addresses_created += 1
            except (ValidationError, NotFoundError) as e:
                warnings.append(f"No se pudo crear address envío: {e}")

        # 5. Crear contacts
        contacts_created = 0
        for contact in registration.contacts:
            try:
                self._create_contact(customer_name, contact)
                contacts_created += 1
            except (ValidationError, NotFoundError) as e:
                warnings.append(f"No se pudo crear contact '{contact.name}': {e}")

        log.info(
            "erpnext.register_customer.ok",
            erp_customer_id=customer_name,
            addresses=addresses_created,
            contacts=contacts_created,
            warnings=len(warnings),
        )

        return CustomerRegistrationResult(
            erp_customer_id=customer_name,
            erp_customer_url=f"{self.config.base_url}/app/customer/{quote(customer_name)}",
            addresses_created=addresses_created,
            contacts_created=contacts_created,
            warnings=warnings,
            raw_response=r.json().get("data", {}),
        )

    # ---- Customer body ----

    # Mapping de TaxCategory canónica → tax_category de ERPNext (texto libre).
    # ERPNext acepta cualquier string si el Tax Category Doctype existe; usamos
    # nombres estándar que un implementador puede crear con esos valores.
    _TAX_CATEGORY_LABELS = {
        "domestic": "Domestic",
        "eu_intracom": "EU Intracom",
        "export": "Export",
        "unknown": "",
    }

    def _build_customer_body(
        self,
        reg: CanonicalCustomerRegistration,
        *,
        territory_override: str | None = None,
        include_tax_category: bool = True,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "customer_name": reg.company_name,
            "customer_type": "Company",
            "customer_group": self.config.default_customer_group,
            "territory": territory_override
            or reg.fiscal_address.country
            or self.config.default_territory,
        }
        # Tax ID: preferimos eu_vat (intracom) sino tax_id local
        if reg.eu_vat:
            body["tax_id"] = reg.eu_vat
        elif reg.tax_id:
            body["tax_id"] = reg.tax_id

        # Tax category — solo se setea si el caller dice que ERPNext la tiene
        # creada (o se ha auto-creado). Si no, el campo se queda vacío y el
        # implementador puede asignarla manualmente sin que falle el alta.
        if include_tax_category:
            tax_label = self._TAX_CATEGORY_LABELS.get(reg.tax_category, "")
            if tax_label:
                body["tax_category"] = tax_label

        if reg.main_email:
            body["email_id"] = reg.main_email
        if reg.main_phone:
            body["mobile_no"] = reg.main_phone
        if reg.preferred_language:
            body["language"] = reg.preferred_language

        # Custom fields: supplier number + signature audit trail
        if reg.supplier_number_in_customer_system:
            body[self._SUPPLIER_NUMBER_FIELDNAME] = reg.supplier_number_in_customer_system
        if reg.signed_by_name:
            body[self._SIGNED_BY_NAME_FIELDNAME] = reg.signed_by_name
        if reg.signed_by_role:
            body[self._SIGNED_BY_ROLE_FIELDNAME] = reg.signed_by_role
        if reg.signature_date:
            body[self._SIGNATURE_DATE_FIELDNAME] = reg.signature_date.isoformat()

        return body

    # ---- Address creation ----

    def _create_address(
        self,
        customer_name: str,
        addr: CanonicalAddress,
        *,
        address_type: str = "Permanent",
    ) -> None:
        """Crea un Address en ERPNext y lo vincula al Customer via Dynamic Link.

        ERPNext exige que `country` exista como Country doctype. Si el país
        del PDF no matchea, hacemos un best-effort intentando primero el
        nombre tal cual y, si falla, "Spain" como fallback (lo más probable
        para nuestro mercado). El warning se devuelve al caller.
        """
        body = {
            "address_title": f"{customer_name} - {address_type}"[:140],
            "address_type": address_type,
            "address_line1": addr.line1,
            "address_line2": addr.line2,
            "city": addr.city,
            "pincode": addr.postal_code,
            "state": addr.state_or_region,
            "country": addr.country,
            "links": [
                {
                    "link_doctype": "Customer",
                    "link_name": customer_name,
                }
            ],
        }
        try:
            self._post("/api/resource/Address", body)
        except ValidationError as e:
            # País no existe en ERPNext → fallback al territorio default
            if "country" in str(e).lower():
                body["country"] = self.config.default_territory
                self._post("/api/resource/Address", body)
            else:
                raise

    # ---- Contact creation ----

    def _create_contact(self, customer_name: str, contact: CanonicalContact) -> None:
        """Crea un Contact en ERPNext y lo vincula al Customer."""
        # Split del nombre — ERPNext requiere first_name como mínimo
        parts = contact.name.strip().split(maxsplit=1)
        first_name = parts[0] if parts else contact.name
        last_name = parts[1] if len(parts) > 1 else None

        body: dict[str, Any] = {
            "first_name": first_name,
            "last_name": last_name,
            "designation": contact.role,
            "links": [
                {
                    "link_doctype": "Customer",
                    "link_name": customer_name,
                }
            ],
        }
        if contact.email:
            body["email_ids"] = [{"email_id": contact.email, "is_primary": 1}]
        if contact.phone:
            body["phone_nos"] = [{"phone": contact.phone, "is_primary_phone": 1}]

        self._post("/api/resource/Contact", body)

    # ---- Custom fields auxiliares (supplier number + audit trail) ----

    _SUPPLIER_NUMBER_FIELDNAME = "orderflow_supplier_number_in_their_system"
    _SIGNED_BY_NAME_FIELDNAME = "orderflow_registration_signed_by_name"
    _SIGNED_BY_ROLE_FIELDNAME = "orderflow_registration_signed_by_role"
    _SIGNATURE_DATE_FIELDNAME = "orderflow_registration_signature_date"

    # ---- Master data (Territory / Tax Category) auto-creados ----

    def _ensure_territory(self, territory_name: str) -> None:
        """Crea el Territory en ERPNext si no existe.

        ERPNext valida `customer.territory` contra el doctype Territory. El
        setup wizard solo crea algunos territories básicos (Spain, All
        Territories, sus padres). Para clientes de otros países (France,
        Germany, etc.) hay que crearlos al vuelo. Como hijos de
        'All Territories'.
        """
        if not territory_name:
            return
        # Caché en memoria — no consultamos dos veces
        if not hasattr(self, "_territory_cache"):
            self._territory_cache: set[str] = set()
        if territory_name in self._territory_cache:
            return
        # Existe en ERPNext?
        existing = self._get_list(
            "Territory",
            filters=[["name", "=", territory_name]],
            fields=["name"],
        )
        if existing:
            self._territory_cache.add(territory_name)
            return
        # Crear como hijo de All Territories (root)
        self._post(
            "/api/resource/Territory",
            {
                "territory_name": territory_name,
                "parent_territory": "All Territories",
                "is_group": 0,
            },
        )
        self._territory_cache.add(territory_name)
        log.info("erpnext.territory.created", name=territory_name)

    def _ensure_tax_category(self, tax_category_name: str) -> None:
        """Crea la Tax Category en ERPNext si no existe.

        Si el implementador ha definido Tax Rules vinculadas a esa categoría,
        ERPNext aplicará los impuestos correctos automáticamente. Si no, la
        categoría queda como simple etiqueta del cliente — sin daño.
        """
        if not tax_category_name:
            return
        if not hasattr(self, "_tax_category_cache"):
            self._tax_category_cache: set[str] = set()
        if tax_category_name in self._tax_category_cache:
            return
        existing = self._get_list(
            "Tax Category",
            filters=[["name", "=", tax_category_name]],
            fields=["name"],
        )
        if existing:
            self._tax_category_cache.add(tax_category_name)
            return
        self._post(
            "/api/resource/Tax Category",
            {"title": tax_category_name},
        )
        self._tax_category_cache.add(tax_category_name)
        log.info("erpnext.tax_category.created", name=tax_category_name)

    def _ensure_supplier_number_field(self) -> None:
        if getattr(self, "_supplier_number_field_ensured", False):
            return
        existing = self._get_list(
            "Custom Field",
            filters=[
                ["dt", "=", "Customer"],
                ["fieldname", "=", self._SUPPLIER_NUMBER_FIELDNAME],
            ],
        )
        if not existing:
            self._post(
                "/api/resource/Custom Field",
                {
                    "dt": "Customer",
                    "fieldname": self._SUPPLIER_NUMBER_FIELDNAME,
                    "label": "Our supplier number in their system (Order Flow)",
                    "fieldtype": "Data",
                    "insert_after": "tax_id",
                    "description": (
                        "Código que el cliente ha asignado a NUESTRA empresa en SU "
                        "sistema. Útil para matchear pedidos por referencia automatica."
                    ),
                },
            )
        self._supplier_number_field_ensured = True

    def _ensure_signature_fields(self) -> None:
        if getattr(self, "_signature_fields_ensured", False):
            return
        for fieldname, label, fieldtype, insert_after in (
            (self._SIGNED_BY_NAME_FIELDNAME, "Registration signed by", "Data", "tax_id"),
            (
                self._SIGNED_BY_ROLE_FIELDNAME,
                "Registration signed by — role",
                "Data",
                self._SIGNED_BY_NAME_FIELDNAME,
            ),
            (
                self._SIGNATURE_DATE_FIELDNAME,
                "Registration signature date",
                "Date",
                self._SIGNED_BY_ROLE_FIELDNAME,
            ),
        ):
            existing = self._get_list(
                "Custom Field",
                filters=[["dt", "=", "Customer"], ["fieldname", "=", fieldname]],
            )
            if not existing:
                self._post(
                    "/api/resource/Custom Field",
                    {
                        "dt": "Customer",
                        "fieldname": fieldname,
                        "label": label,
                        "fieldtype": fieldtype,
                        "insert_after": insert_after,
                    },
                )
        self._signature_fields_ensured = True

    # =========================================================================
    # Customer / Item bootstrap
    # =========================================================================

    def _lookup_customer_or_fail(self, customer: CanonicalCustomer) -> str:
        """Devuelve el `name` (PK) del Customer en ERPNext.

        Busca en este orden (más específico → más laxo):
            1. Por `tax_id` exacto (eu_vat o cif/nif). Es el match más fiable
               cuando el dato está disponible.
            2. Por `customer_name` exacto.
            3. Por `customer_name` normalizado (sin mayúsculas, sin sufijos
               sociales típicos como SAS/SARL/SA/SL/SLU/SAU).

        Si nada coincide, lanza `CustomerNotRegisteredError` con la lista de
        intentos para que el caller pueda comunicarlo al usuario.
        """
        hints: list[str] = []

        # 1. Por tax_id exacto (eu_vat o cif/nif)
        for tax_value in (customer.eu_vat, customer.tax_id):
            if not tax_value:
                continue
            normalized_tax = tax_value.replace(" ", "").upper()
            hints.append(f"tax_id={normalized_tax}")
            for raw in (tax_value, normalized_tax):
                results = self._get_list(
                    "Customer", filters=[["tax_id", "=", raw]], fields=["name"]
                )
                if results:
                    return results[0]["name"]

        # 2. Por customer_name exacto
        hints.append(f"customer_name='{customer.name}'")
        results = self._get_list(
            "Customer", filters=[["customer_name", "=", customer.name]], fields=["name"]
        )
        if results:
            return results[0]["name"]

        # 3. Por customer_name normalizado (busca con `like` por si en el ERP
        # está con sufijo social que el PDF no trae, o viceversa).
        normalized = _normalize_company_name(customer.name)
        hints.append(f"normalized='{normalized}'")
        if normalized:  # evita LIKE '%%' si el nombre era solo sufijos (raro)
            results = self._get_list(
                "Customer",
                filters=[["customer_name", "like", f"%{normalized}%"]],
                fields=["name", "customer_name"],
            )
            for r in results:
                if _normalize_company_name(r["customer_name"]) == normalized:
                    return r["name"]

        raise CustomerNotRegisteredError(customer_name=customer.name, lookup_hints=hints)

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


# =============================================================================
# Helpers de normalización
# =============================================================================

# Sufijos sociales que aparecen al final de razones sociales y NO discriminan
# entre empresas distintas (Rubix Nord vs Rubix Nord SAS son la misma).
# Los comparamos sin puntos ni comas para que "S.A.U." == "SAU".
_COMPANY_SUFFIXES = {
    "sas",
    "sarl",
    "sa",
    "sl",
    "slu",
    "sau",
    "sasu",
    "gmbh",
    "ag",
    "ug",
    "ltd",
    "ltda",
    "inc",
    "llc",
    "lp",
    "llp",
    "bv",
    "nv",
    "spa",
    "srl",
    "oy",
    "ab",
}


def _normalize_company_name(name: str) -> str:
    """Normaliza una razón social para comparaciones aproximadas.

    - lowercase
    - quita espacios extra
    - quita sufijos sociales finales (SAS, SARL, SA, SL, SLU, SAU, S.A.U., GmbH...)
      ignorando puntuación.
    """
    s = " ".join(name.lower().strip().split())
    parts = s.split()
    while parts:
        # Quitar puntos y comas para comparar contra el set
        stripped = parts[-1].replace(".", "").replace(",", "")
        if stripped in _COMPANY_SUFFIXES:
            parts.pop()
        else:
            break
    return " ".join(parts)
