"""Clasificación pedido / oferta / ficha cliente basada en heurísticas + sugerencia de Claude.

Heurística filename (rápida, gratis, determinística):
- Patrón `TL\\d{6}-\\d+` en el nombre → OFERTA Quimilock (las ofertas siempre
  llevan ese formato en el filename).
- Keywords "registration", "alta cliente", "fiche client" → FICHA_CLIENTE
- Keywords "Offre", "Devis", "Quote", "Oferta", "Cotización", "Presupuesto" → OFERTA
- Keywords "Commande", "Order", "Pedido", "Purchase", "PO_", "_PO" → PEDIDO

Si la heurística decide, gana sobre Claude. Si no decide, se usa la sugerencia
de Claude del JSON extraído. Si nada lo identifica → DESCONOCIDO.
"""

from __future__ import annotations

import re

from app.models.document import DocumentType

# Patrón de número de oferta Quimilock (el filename de las ofertas SIEMPRE lo lleva)
OFFER_NUMBER_PATTERN = re.compile(r"TL\d{6}-\d+", re.IGNORECASE)

OFFER_KEYWORDS = (
    "offre",
    "devis",
    "oferta",
    "quote",
    "proposal",
    "cotizacion",
    "cotización",
    "presupuesto",
    "angebot",
)

ORDER_KEYWORDS = (
    "commande",
    "pedido",
    "order",
    "purchase",
    "po-",
    "po_",
    "_po_",
    "_po.",
    "bestellung",
    "bon-de-commande",
    "boncommande",
)

# Ficha de alta de cliente — palabras clave en filename que la identifican.
# Multi-idioma porque las fichas de Quimilock vienen en FR/EN/ES.
CUSTOMER_REGISTRATION_KEYWORDS = (
    "customer registration",
    "customer-registration",
    "customer_registration",
    "alta cliente",
    "alta-cliente",
    "alta_cliente",
    "alta de cliente",
    "ficha cliente",
    "ficha-cliente",
    "ficha_cliente",
    "ficha de cliente",
    "ficha de alta",
    "fiche client",
    "fiche-client",
    "fiche_client",
    "kundendaten",  # alemán
    "kunden-erfassung",
    "datos cliente",
)


def classify_by_filename(filename: str | None) -> DocumentType | None:
    """Devuelve el tipo si el filename es decisivo, None si ambiguo."""
    if not filename:
        return None

    # 1. Patrón de número de oferta — más fuerte
    if OFFER_NUMBER_PATTERN.search(filename):
        return DocumentType.OFERTA

    name = filename.lower()

    # 2. Ficha de alta de cliente — chequear ANTES que pedido/oferta porque
    # algunas fichas pueden contener la palabra "client" que también está en
    # algunos filenames de pedidos.
    has_registration_kw = any(kw in name for kw in CUSTOMER_REGISTRATION_KEYWORDS)
    if has_registration_kw:
        return DocumentType.FICHA_CLIENTE

    # 3. Keywords explícitas pedido/oferta
    has_offer_kw = any(kw in name for kw in OFFER_KEYWORDS)
    has_order_kw = any(kw in name for kw in ORDER_KEYWORDS)

    if has_offer_kw and not has_order_kw:
        return DocumentType.OFERTA
    if has_order_kw and not has_offer_kw:
        return DocumentType.PEDIDO

    return None


def classify_by_extracted_json(extracted_json: dict | None) -> DocumentType | None:
    """Saca el tipo del JSON que devolvió Claude."""
    if not extracted_json:
        return None
    raw = (extracted_json.get("document_type") or "").lower().strip().replace(" ", "_")
    if raw == "pedido":
        return DocumentType.PEDIDO
    if raw == "oferta":
        return DocumentType.OFERTA
    if raw in ("ficha_cliente", "ficha_de_cliente", "alta_cliente", "customer_registration"):
        return DocumentType.FICHA_CLIENTE
    if raw == "albaran" or raw == "albarán":
        return DocumentType.ALBARAN
    if raw == "factura":
        return DocumentType.FACTURA
    if raw == "desconocido":
        return DocumentType.DESCONOCIDO
    # También intentar deducir si tiene numero_oferta sin numero_pedido_cliente
    pedido_meta = extracted_json.get("pedido") or {}
    if isinstance(pedido_meta, dict):
        num_offer = pedido_meta.get("numero_oferta")
        num_order = pedido_meta.get("numero_pedido_cliente")
        if num_offer and OFFER_NUMBER_PATTERN.search(num_offer) and not num_order:
            return DocumentType.OFERTA
    return None


def classify_document(
    *,
    filename: str | None,
    extracted_json: dict | None = None,
) -> DocumentType:
    """Clasifica usando filename (gana) → JSON Claude → fallback PEDIDO.

    Asumimos PEDIDO por defecto cuando hay contenido extraído pero ninguna
    señal indica oferta. Razón: el buzón de María solo recibe ofertas y pedidos,
    así que descartar oferta implica que es pedido.

    Solo devolvemos DESCONOCIDO si NO hay contenido (ni filename ni extracted_json).
    """
    by_name = classify_by_filename(filename)
    if by_name is not None:
        return by_name
    by_json = classify_by_extracted_json(extracted_json)
    if by_json is not None:
        return by_json
    # Fallback: si tenemos algo de contenido, asumir pedido. Si no, desconocido.
    if filename or extracted_json:
        return DocumentType.PEDIDO
    return DocumentType.DESCONOCIDO
