"""Extracción IA de pedidos PDF.

Pipeline (revisado tras añadir OCR):
    PDF bytes
      ↓ OCRProvider (Mistral OCR)
    markdown estructurado + páginas
      ↓ Claude Sonnet 4.6 (recibe markdown, NO PDF crudo)
    JSON estructurado + source_texts (fragmento original por campo)

source_texts permite a la UI resaltar qué texto del PDF corresponde a cada campo
del JSON, sin necesidad de bounding boxes (que se calculan en frontend con
pdf.js text layer + búsqueda).

Lecciones del workflow n8n original:
- Anti-contaminación de refs (TF-75 ≠ TF-751, GF-1 ≠ GF-11)
- Preserva exactamente el código que aparece, sin "corregir" hacia variantes
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


SYSTEM_PROMPT = """Eres un extractor de pedidos industriales en formato pedido cliente / oferta / bon de commande.

Recibirás texto MARKDOWN extraído por OCR (Mistral) sobre un PDF. El markdown puede contener varias páginas separadas por la marca `---PAGE---`. Las tablas vienen ya formateadas en sintaxis markdown.

Tu tarea: leer el markdown y devolver un JSON con la estructura definida más abajo.

REGLAS CRÍTICAS:

0. **Detecta el TIPO de documento** (`document_type`):
   - `oferta` → es una propuesta comercial emitida por el VENDEDOR hacia el CLIENTE.
       Pistas: "Devis", "Offre", "Oferta", "Quote", "Proposal", "Cotización",
       "validez/validity/valable jusqu'au", número de oferta tipo `TL[YYMMDD]-[NC]`,
       no menciona ningún PO/pedido de cliente.
   - `pedido` → es una orden de compra emitida por el CLIENTE hacia el VENDEDOR.
       Pistas: "Bon de commande", "Purchase Order", "PO", "Pedido", "Commande",
       "Order", número de pedido del cliente claramente identificado, posibles
       campos "Date de livraison souhaitée", "Délai", "Acknowledge by".
   - `desconocido` → si no hay señales claras (no inventes).

1. **Identifica al CLIENTE correcto.**
   El "cliente" es la empresa que EMITE el pedido (quien compra). NO es la empresa
   que aparece destacada como destinataria/receptora del pedido (quien vende).
   - Busca encabezados tipo "Cliente:", "From:", "De:", "Pedido de:".
   - Si una misma empresa aparece como destinataria/proveedora (membrete superior,
     logo, dirección de envío) NO debe ir en `cliente`.

2. **Preserva las referencias EXACTAMENTE como aparecen.**
   - NO "corrijas" códigos hacia variantes parecidas. TF-75 ≠ TF-751. GF-1 ≠ GF-11. T-A ≠ T-AT.
   - Si la referencia es ambigua, devuelve null en `referencia` y el texto crudo en `descripcion`.
   - **Si una línea muestra DOS códigos** (uno del cliente y uno del proveedor), prioriza el del **PROVEEDOR/VENDOR** — esa es la referencia que usamos para vender. Pistas que identifican la ref del proveedor: "Ref interne", "Internal ref", "Référence fournisseur", "Vendor ref", "Vendor PN", "Supplier ref", "Notre référence", "Our ref", "SKU". Ejemplo: `"GE000002 Ref Interne: DEB-01"` → `referencia="DEB-01"` (NO `GE000002`, que es el código interno del cliente).
   - El código del CLIENTE (Customer PN, Buyer ref) puede ir en `descripcion` para no perderlo.

3. **Cantidades y precios literales.**
   - Cantidades como números (sin separador de miles).
   - Precios en formato decimal con punto (12.50, no 12,50).
   - Si el PDF separa HT/TTC, prioriza HT (sin IVA).
   - Si no hay precio explícito, devuelve null.

4. **Unidades literales.** ML, M2, UD, KG, L, PCS, CAJA — sin normalizar.

5. **Fechas en formato ISO 8601** (YYYY-MM-DD). Convierte si vienen en europeo (DD/MM/YYYY).

6. **Si un campo no está, devuelve null** — NO inventes valores plausibles.

7. **source_texts**: para cada campo extraído, incluye un fragmento textual EXACTO
   copiado del markdown que justifica el valor. La UI lo usa para resaltar el origen.
   - Para valores derivados/calculados (totales agregados), source_text puede ser null.
   - El fragmento debe ser corto (<150 chars), preservando mayúsculas/símbolos.

8. **CIF/NIF vs Nº IVA intracomunitario**:
   - `cif_nif`: identificador fiscal nacional (ej: `B12345678` en España, `SIRET` francés).
   - `numero_iva`: número de IVA intracomunitario (ej: `ESB12345678`, `FR40123456789`).
   - Si solo aparece uno y no se puede distinguir, ponlo en `cif_nif`.

9. **Direcciones — entrega vs facturación**:
   - `direccion_entrega`: a dónde se envía la mercancía ("Ship to", "Livraison", "Entrega").
   - `direccion_facturacion`: a dónde se envía la factura ("Bill to", "Facturation", "Facturación").
   - Si solo hay UNA dirección sin distinción, ponla en `direccion_entrega` y deja `direccion_facturacion` en null.

10. **Transporte / portes** (`totales.transporte`, número o null):
    - Si el documento menciona portes/transport/freight con un IMPORTE explícito → ese importe.
    - Si menciona transporte como "incluido"/"included"/"port payé" sin importe → 0.
    - Si NO menciona transporte en absoluto → null.
    - Pistas multilingües: "Frais de port", "FP", "Transport", "Portes", "Shipping", "Freight".

ESTRUCTURA JSON A DEVOLVER:

{
  "document_type": "pedido" | "oferta" | "desconocido",
  "cliente": {
    "nombre": string | null,
    "cif_nif": string | null,
    "numero_iva": string | null,
    "direccion_entrega": string | null,
    "direccion_facturacion": string | null,
    "contacto_email": string | null
  },
  "pedido": {
    "numero_pedido_cliente": string | null,
    "numero_oferta": string | null,
    "fecha_pedido": "YYYY-MM-DD" | null,
    "fecha_entrega_solicitada": "YYYY-MM-DD" | null,
    "moneda": "EUR" | "USD" | string | null,
    "observaciones": string | null
  },
  "lineas": [
    {
      "referencia": string | null,
      "descripcion": string,
      "cantidad": number,
      "unidad": string | null,
      "precio_unitario": number | null,
      "importe_linea": number | null
    }
  ],
  "totales": {
    "subtotal_ht": number | null,
    "transporte": number | null,
    "iva": number | null,
    "total_ttc": number | null
  },
  "confianza_global": "alta" | "media" | "baja",
  "notas_extraccion": string | null,
  "source_texts": {
    "cliente.nombre": string | null,
    "cliente.cif_nif": string | null,
    "cliente.numero_iva": string | null,
    "cliente.direccion_entrega": string | null,
    "cliente.direccion_facturacion": string | null,
    "cliente.contacto_email": string | null,
    "pedido.numero_pedido_cliente": string | null,
    "pedido.numero_oferta": string | null,
    "pedido.fecha_pedido": string | null,
    "pedido.fecha_entrega_solicitada": string | null,
    "pedido.moneda": string | null,
    "pedido.observaciones": string | null,
    "totales.transporte": string | null,
    "lineas.0.referencia": string | null,
    "lineas.0.descripcion": string | null,
    "lineas.1.referencia": string | null,
    "lineas.1.descripcion": string | null
  }
}

Si te paso CAMPOS CUSTOM DEL TENANT más abajo, añade también un bloque `"custom"`:
  "custom": { "<key_custom>": string | null, ... }
Solo incluye keys del listado custom. Deja el valor en null si no aparece en el documento.

Devuelve SOLO el JSON, sin texto previo ni explicaciones, sin envolver en ```json.
"""


class ClienteData(BaseModel):
    nombre: str | None = None
    cif_nif: str | None = None
    numero_iva: str | None = None
    direccion_entrega: str | None = None
    direccion_facturacion: str | None = None
    contacto_email: str | None = None


class PedidoMeta(BaseModel):
    numero_pedido_cliente: str | None = None
    numero_oferta: str | None = None
    fecha_pedido: date | None = None
    fecha_entrega_solicitada: date | None = None
    moneda: str | None = None
    observaciones: str | None = None


class LineaPedido(BaseModel):
    referencia: str | None = None
    descripcion: str
    cantidad: float
    unidad: str | None = None
    precio_unitario: float | None = None
    importe_linea: float | None = None


class TotalesPedido(BaseModel):
    subtotal_ht: float | None = None
    transporte: float | None = (
        None  # null = no mencionado · 0 = mencionado sin coste · >0 = importe
    )
    iva: float | None = None
    total_ttc: float | None = None


class CustomField(BaseModel):
    """Campo añadido manualmente por el revisor (zona del PDF etiquetada)."""

    name: str
    value: str | None = None
    source_text: str | None = None  # fragmento original del PDF (para overlay)


class ExtractionResult(BaseModel):
    document_type: str = "desconocido"  # pedido | oferta | desconocido
    cliente: ClienteData = Field(default_factory=ClienteData)
    pedido: PedidoMeta = Field(default_factory=PedidoMeta)
    lineas: list[LineaPedido] = Field(default_factory=list)
    totales: TotalesPedido = Field(default_factory=TotalesPedido)
    confianza_global: str = "media"
    notas_extraccion: str | None = None
    source_texts: dict[str, str | None] = Field(default_factory=dict)
    # Campos custom definidos por el tenant (tabla TenantField). Claude los rellena
    # según el prompt extendido. Plano: {key_snake_case: valor_string}.
    custom: dict[str, str | None] = Field(default_factory=dict)
    # Campos custom añadidos manualmente por el revisor (zona del PDF etiquetada).
    custom_fields: list[CustomField] = Field(default_factory=list)


class ExtractionError(Exception):
    """Error no recuperable de la extracción IA."""


class ExtractionService:
    """Extrae JSON estructurado a partir de markdown OCR usando Claude."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = api_key or settings.anthropic_api_key
        self.model = model or settings.anthropic_model
        if not self.api_key:
            raise ExtractionError("ANTHROPIC_API_KEY no configurada")

    def extract(
        self,
        markdown: str,
        *,
        tenant_context: str | None = None,
        field_aliases: dict[str, list[str]] | None = None,
        custom_field_specs: list[tuple[str, str, str | None]] | None = None,
    ) -> ExtractionResult:
        """Extrae JSON estructurado del markdown.

        - `tenant_context`: texto libre inyectado al prompt (ej: "Tu empresa es Quimilock").
        - `field_aliases`: pistas {field_path: [labels conocidos en el PDF]} para que
          Claude reconozca etiquetas multi-idioma del tenant.
        - `custom_field_specs`: lista de campos custom del tenant a extraer al bloque
          `custom`. Cada item es `(key_snake_case, label_humano, descripcion?)`.
        """
        from anthropic import Anthropic

        if not markdown.strip():
            raise ExtractionError("Markdown vacío — el OCR no produjo texto")

        client = Anthropic(api_key=self.api_key)

        log.info(
            "extraction.start",
            model=self.model,
            markdown_chars=len(markdown),
            field_aliases=sum(len(v) for v in (field_aliases or {}).values()),
        )

        system_blocks: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        if tenant_context:
            system_blocks.append(
                {
                    "type": "text",
                    "text": f"CONTEXTO DEL TENANT:\n{tenant_context}",
                }
            )
        if field_aliases:
            lines = [
                "PISTAS DEL TENANT (etiquetas reconocidas en este buzón):",
                "Si encuentras alguna de estas etiquetas en el documento, el valor",
                "que las acompaña corresponde al campo canónico indicado.",
                "",
            ]
            for field, labels in sorted(field_aliases.items()):
                if labels:
                    joined = ", ".join(f'"{label}"' for label in sorted(set(labels)))
                    lines.append(f"- {joined} → {field}")
            system_blocks.append({"type": "text", "text": "\n".join(lines)})
        if custom_field_specs:
            lines = [
                "CAMPOS CUSTOM DEL TENANT (intenta extraer cada uno como string en el bloque `custom`):",
                "Devuelve null si el campo no aparece en el documento — NO inventes.",
                "",
            ]
            for key, label, desc in custom_field_specs:
                if desc:
                    lines.append(f'- "{key}" — {label}: {desc}')
                else:
                    lines.append(f'- "{key}" — {label}')
            system_blocks.append({"type": "text", "text": "\n".join(lines)})

        user_text = (
            "Markdown del PDF (OCR Mistral). Extrae el JSON siguiendo las reglas.\n\n"
            f"```markdown\n{markdown}\n```"
        )

        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_blocks,
                messages=[{"role": "user", "content": user_text}],
            )
        except Exception as e:
            log.error("extraction.api_error", error=str(e))
            raise ExtractionError(f"Anthropic API error: {e}") from e

        raw_text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        log.info(
            "extraction.api_ok",
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_read=getattr(response.usage, "cache_read_input_tokens", 0),
            cache_write=getattr(response.usage, "cache_creation_input_tokens", 0),
        )

        return self._parse(raw_text)

    @staticmethod
    def _parse(raw: str) -> ExtractionResult:
        """Parsea el JSON crudo. Tolera fences ```json``` por si Claude se rebela."""
        text = raw.strip()
        if text.startswith("```"):
            text = text.removeprefix("```json").removeprefix("```").rstrip()
            if text.endswith("```"):
                text = text[:-3].rstrip()

        try:
            payload: dict[str, Any] = json.loads(text)
        except json.JSONDecodeError as e:
            log.error("extraction.json_parse_failed", error=str(e), raw=raw[:500])
            raise ExtractionError(f"Invalid JSON from model: {e}") from e

        try:
            return ExtractionResult.model_validate(payload)
        except Exception as e:
            log.error("extraction.schema_validation_failed", error=str(e))
            raise ExtractionError(f"Schema validation failed: {e}") from e
