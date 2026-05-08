"""Vista agregada de clientes desde la perspectiva de Order Flow.

Construye una "vista de cliente" agregando documentos por cliente:
- Pedidos / ofertas / fichas asociados a cada cliente.
- Estado de alta: ¿hay una ficha que se dio de alta en el ERP? ¿erp_id?
- KPIs: nº pedidos, importe acumulado, último pedido.

NO es un endpoint CRUD de clientes — los clientes "viven" en el ERP. Esta
vista es solo lectura, agregando lo que Order Flow ya tiene.

Identidad del cliente: agrupamos por VAT/tax_id si está disponible (más
fiable), si no por customer_name normalizado. Algoritmo en
`_canonical_customer_key`.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_current_tenant_id
from app.core.db import get_session
from app.models.document import Document, DocumentStatus, DocumentType

router = APIRouter(prefix="/customers", tags=["customers"])


# Sufijos que removemos al normalizar nombres para deduplicación
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


def _normalize_name(name: str) -> str:
    """Normaliza un nombre quitando puntuación, lowercase y sufijos sociales."""
    s = " ".join(name.lower().strip().split())
    parts = s.split()
    while parts:
        stripped = parts[-1].replace(".", "").replace(",", "")
        if stripped in _COMPANY_SUFFIXES:
            parts.pop()
        else:
            break
    return " ".join(parts)


def _normalize_vat(vat: str | None) -> str | None:
    if not vat:
        return None
    return re.sub(r"[\s\-./]", "", vat).upper() or None


def _canonical_customer_key(extracted: dict[str, Any] | None) -> tuple[str, str] | None:
    """Devuelve (key_type, key_value) que identifica un cliente.

    Preferimos VAT/tax_id si está disponible. Si no, nombre normalizado.
    Devuelve None si el doc no tiene info de cliente.
    """
    if not isinstance(extracted, dict):
        return None

    # Detectar si es ficha (tiene company_name top-level) o pedido/oferta
    # (tiene cliente.nombre).
    if "company_name" in extracted:
        # Ficha de alta
        eu_vat = _normalize_vat(extracted.get("eu_vat"))
        if eu_vat:
            return ("vat", eu_vat)
        tax_id = _normalize_vat(extracted.get("tax_id"))
        if tax_id:
            return ("tax_id", tax_id)
        name = (extracted.get("company_name") or "").strip()
        if name:
            return ("name", _normalize_name(name))
        return None

    # Pedido/oferta — estructura `cliente.{nombre,cif_nif,numero_iva}`
    cliente = extracted.get("cliente") or {}
    if not isinstance(cliente, dict):
        return None
    eu_vat = _normalize_vat(cliente.get("numero_iva"))
    if eu_vat:
        return ("vat", eu_vat)
    cif = _normalize_vat(cliente.get("cif_nif"))
    if cif:
        return ("tax_id", cif)
    nombre = (cliente.get("nombre") or "").strip()
    if nombre:
        return ("name", _normalize_name(nombre))
    return None


def _customer_display_name(extracted: dict[str, Any] | None) -> str | None:
    if not isinstance(extracted, dict):
        return None
    # Preferimos company_name (ficha) sobre cliente.nombre (pedido)
    if extracted.get("company_name"):
        return str(extracted["company_name"]).strip()
    cliente = extracted.get("cliente")
    if isinstance(cliente, dict) and cliente.get("nombre"):
        return str(cliente["nombre"]).strip()
    return None


def _doc_total_ttc(extracted: dict[str, Any] | None) -> float | None:
    """Saca el importe TTC del extracted_json de un pedido."""
    if not isinstance(extracted, dict):
        return None
    totales = extracted.get("totales")
    if not isinstance(totales, dict):
        return None
    v = totales.get("total_ttc")
    if isinstance(v, int | float):
        return float(v)
    return None


# =============================================================================
# Schemas de respuesta
# =============================================================================


class CustomerSummary(BaseModel):
    """Resumen agregado de un cliente (no es un row de DB — se construye on-the-fly)."""

    # Identidad
    key: str  # tipo:valor (e.g. "vat:FR76344020383", "name:rubix nord")
    display_name: str
    eu_vat: str | None = None
    tax_id: str | None = None

    # Estado de alta en el ERP
    # 3 estados posibles, mutuamente excluyentes:
    #   "in_erp"        → has_extracted_registration && is_registered_in_erp
    #   "ready_to_register" → has_extracted_registration && !is_registered_in_erp
    #   "no_registration_form" → !has_extracted_registration
    registration_status: str = "no_registration_form"
    is_registered_in_erp: bool = False
    erp_customer_id: str | None = None
    erp_customer_url: str | None = None
    registration_document_id: UUID | None = None  # la ficha de alta (si existe)

    # Conteos
    pedidos_count: int = 0
    pedidos_approved_count: int = 0
    pedidos_pushed_to_erp_count: int = 0
    ofertas_count: int = 0
    fichas_count: int = 0

    # Económico
    total_amount_approved: float = 0.0
    currency: str = "EUR"

    # Actividad
    last_activity_at: datetime | None = None
    first_seen_at: datetime | None = None


class CustomerListResponse(BaseModel):
    customers: list[CustomerSummary]
    total: int


# =============================================================================
# Endpoint
# =============================================================================


@router.get("", response_model=CustomerListResponse)
def list_customers(
    tenant_id: Annotated[UUID, Depends(get_current_tenant_id)],
    session: Annotated[Session, Depends(get_session)],
) -> CustomerListResponse:
    """Lista de clientes agregados desde los documentos del tenant.

    Cada cliente se identifica por:
        1. VAT intracomunitario (preferido)
        2. CIF/NIF local
        3. Razón social normalizada (sin sufijos sociales)

    Esto deduplicará automáticamente "RUBIX Nord" y "RUBIX Nord SAS" si
    comparten VAT, y mostrará su histórico unificado.
    """
    # Cargamos todos los docs del tenant (lite — sin ocr_result/raw_text)
    docs = list(session.exec(select(Document).where(Document.tenant_id == tenant_id)).all())

    customers: dict[str, CustomerSummary] = {}

    for d in docs:
        ext = d.extracted_json
        key_pair = _canonical_customer_key(ext)
        if key_pair is None:
            continue
        key = f"{key_pair[0]}:{key_pair[1]}"

        # Inicializar entry si es nuevo
        if key not in customers:
            display = _customer_display_name(ext) or key_pair[1]
            eu_vat = None
            tax_id = None
            if isinstance(ext, dict):
                if "company_name" in ext:
                    eu_vat = ext.get("eu_vat")
                    tax_id = ext.get("tax_id")
                else:
                    cliente = ext.get("cliente") or {}
                    if isinstance(cliente, dict):
                        eu_vat = cliente.get("numero_iva")
                        tax_id = cliente.get("cif_nif")
            customers[key] = CustomerSummary(
                key=key,
                display_name=display,
                eu_vat=eu_vat,
                tax_id=tax_id,
            )

        c = customers[key]

        # Conteos por tipo
        if d.document_type == DocumentType.PEDIDO:
            c.pedidos_count += 1
            if d.status == DocumentStatus.APPROVED:
                c.pedidos_approved_count += 1
                ttc = _doc_total_ttc(ext)
                if ttc:
                    c.total_amount_approved += ttc
            if d.erp_id:
                c.pedidos_pushed_to_erp_count += 1
        elif d.document_type == DocumentType.OFERTA:
            c.ofertas_count += 1
        elif d.document_type == DocumentType.FICHA_CLIENTE:
            c.fichas_count += 1
            # Guardamos siempre el ID de la ficha — incluso si no está dada
            # de alta (para linkear en la UI 'Ficha lista para dar de alta').
            if c.registration_document_id is None:
                c.registration_document_id = d.id
            # Si la ficha fue dada de alta (erp_id presente) → marcar registrado
            if d.erp_id and not c.is_registered_in_erp:
                c.is_registered_in_erp = True
                c.erp_customer_id = d.erp_id
                c.erp_customer_url = d.erp_url
                # Esta ficha gana — ID concreto del que SE dio de alta
                c.registration_document_id = d.id

        # Actividad (ventana de fechas)
        if d.created_at:
            if c.first_seen_at is None or d.created_at < c.first_seen_at:
                c.first_seen_at = d.created_at
            if c.last_activity_at is None or d.created_at > c.last_activity_at:
                c.last_activity_at = d.created_at

    # Calcular registration_status ahora que tenemos los conteos finales
    for c in customers.values():
        if c.is_registered_in_erp:
            c.registration_status = "in_erp"
        elif c.fichas_count > 0:
            c.registration_status = "ready_to_register"
        else:
            c.registration_status = "no_registration_form"

    # Ordenamos por última actividad (más reciente primero)
    sorted_customers = sorted(
        customers.values(),
        key=lambda c: c.last_activity_at or datetime.min,
        reverse=True,
    )

    return CustomerListResponse(customers=sorted_customers, total=len(sorted_customers))
