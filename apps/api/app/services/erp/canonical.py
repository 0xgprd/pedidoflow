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


# =============================================================================
# Alta de cliente (registración) — modelos completos
# =============================================================================


class CanonicalAddress(BaseModel):
    """Dirección postal estructurada. Mismo modelo para fiscal, facturación
    y envío — la diferencia se determina por el campo donde se asigna."""

    model_config = ConfigDict(frozen=True)

    line1: str = Field(..., description="Dirección principal (calle + número)")
    line2: str | None = Field(None, description="2ª línea (piso, edificio, polígono...)")
    city: str
    postal_code: str
    state_or_region: str | None = Field(
        None, description="Provincia (ES) / Département (FR) / Bundesland (DE) / etc."
    )
    country: str = Field(..., description="Nombre del país en castellano o ISO-2 (ES, FR, DE...)")


class CanonicalContact(BaseModel):
    """Persona de contacto del cliente (comercial, administrativo, técnico...)."""

    model_config = ConfigDict(frozen=True)

    name: str
    role: str | None = Field(None, description="Función / cargo (e.g. 'Director Comercial')")
    phone: str | None = None
    email: str | None = None


# Categoría fiscal — determina qué impuestos aplica el ERP automáticamente.
# - "domestic": cliente del mismo país que la empresa → IVA normal.
# - "eu_intracom": cliente UE con VAT válido → IVA 0% por inversión sujeto pasivo.
# - "export": cliente fuera de UE → IVA 0% por exportación.
# - "unknown": cuando no se puede deducir (sin VAT y país desconocido).
TaxCategory = Literal["domestic", "eu_intracom", "export", "unknown"]


class CanonicalCustomerRegistration(BaseModel):
    """Datos completos para dar de alta un cliente en el ERP.

    Más rico que `CanonicalCustomer` (que solo lleva lo mínimo para un pedido):
    incluye direcciones estructuradas, varios contactos, datos comerciales y
    de auditoría (firmante de la ficha).

    Pensado para el flujo: PDF ficha de alta → extracción IA → este modelo →
    `adapter.register_customer(...)` → Customer en el ERP con todo.
    """

    model_config = ConfigDict(frozen=True)

    # Trazabilidad — vincula el cliente del ERP con el doc Order Flow del que salió
    source_document_id: UUID = Field(..., description="documents.id de Order Flow")

    # Identidad legal y comercial
    company_name: str = Field(..., description="Razón social / nombre comercial")
    fiscal_name: str | None = Field(
        None, description="Razón social fiscal si distinta del nombre comercial"
    )
    tax_id: str | None = Field(None, description="CIF/NIF/NIE local (sin código país)")
    eu_vat: str | None = Field(
        None, description="VAT intracomunitario con código país (FRxxxx, ESxxxx, ...)"
    )
    # "Supplier Nr." en la ficha de Quimilock — el código que el cliente ha
    # asignado a NUESTRA empresa en SU sistema. Cuando ese cliente envía un
    # pedido lo lleva como referencia → matching automático sin nombre.
    supplier_number_in_customer_system: str | None = Field(
        None,
        description="Código que el cliente nos ha asignado como proveedor en su ERP",
    )

    # Direcciones
    fiscal_address: CanonicalAddress = Field(
        ..., description="Domicilio fiscal — siempre presente, base legal"
    )
    billing_address: CanonicalAddress | None = Field(
        None, description="Dirección de facturación si distinta de la fiscal"
    )
    shipping_address: CanonicalAddress | None = Field(
        None, description="Dirección de envío por defecto si distinta de la fiscal"
    )

    # Contacto principal (a nivel empresa)
    main_phone: str | None = None
    secondary_phone: str | None = None
    fax: str | None = None
    main_email: str | None = None

    # Contactos personales (lista — puede haber varios)
    contacts: list[CanonicalContact] = Field(default_factory=list)

    # Categoría fiscal — la deduce el clasificador IA o el caller
    tax_category: TaxCategory = "unknown"

    # Condiciones comerciales (default impuesto por la empresa que da de alta)
    payment_terms: str | None = Field(None, description="e.g. 'Transferencia 30 días', 'Contado'")
    bank_account_iban: str | None = Field(None, description="IBAN para domiciliaciones del cliente")

    # Idioma preferido del cliente — para imprimir documentos en su idioma
    preferred_language: str | None = Field(
        None, description="ISO 639-1 ('es', 'fr', 'en', 'de', 'it')"
    )

    # Auditoría de la ficha — quién firmó y cuándo
    signed_by_name: str | None = None
    signed_by_role: str | None = None
    signature_date: date | None = None


def deduce_tax_category(
    eu_vat: str | None,
    tax_id: str | None,
    country: str | None,
    home_country_code: str = "ES",
) -> TaxCategory:
    """Deduce la categoría fiscal del cliente a partir de los datos disponibles.

    Reglas:
        - Si el VAT empieza por el código del país de origen (ES por defecto)
          o el `tax_id` parece un CIF/NIF español (letra inicial) → "domestic".
        - Si el VAT empieza por código UE distinto del propio → "eu_intracom".
        - Si tiene país y NO está en UE → "export".
        - En otro caso → "unknown".
    """
    eu_codes = {
        "AT",
        "BE",
        "BG",
        "CY",
        "CZ",
        "DE",
        "DK",
        "EE",
        "EL",
        "ES",
        "FI",
        "FR",
        "HR",
        "HU",
        "IE",
        "IT",
        "LT",
        "LU",
        "LV",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SE",
        "SI",
        "SK",
    }
    home = home_country_code.upper()

    if eu_vat:
        prefix = eu_vat.strip()[:2].upper()
        if prefix == home:
            return "domestic"
        if prefix in eu_codes:
            return "eu_intracom"
        # VAT con prefijo no UE → cliente fuera de UE
        return "export"

    if tax_id:
        # Heurística rápida: CIF/NIF ES típicamente empieza por letra
        # (A/B/C/.../Y) o el formato 8-dígitos+letra (NIE: X/Y/Z + 7 + letra).
        first = tax_id.strip()[:1].upper()
        if first.isalpha() and home == "ES":
            return "domestic"

    if country:
        # Mapa minimal de nombres de país → ISO. Si tu negocio se expande a
        # más mercados, ampliar aquí o usar pycountry.
        country_to_iso = {
            "españa": "ES",
            "spain": "ES",
            "francia": "FR",
            "france": "FR",
            "alemania": "DE",
            "germany": "DE",
            "deutschland": "DE",
            "italia": "IT",
            "italy": "IT",
            "portugal": "PT",
            "reino unido": "GB",
            "united kingdom": "GB",
            "uk": "GB",
            "estados unidos": "US",
            "united states": "US",
            "usa": "US",
        }
        iso = country_to_iso.get(country.strip().lower())
        if iso == home:
            return "domestic"
        if iso in eu_codes:
            return "eu_intracom"
        if iso:  # país conocido pero no UE
            return "export"

    return "unknown"
