"""Validación de pedidos contra catálogo de precios mínimos.

Reglas (ver memory/project_quimilock_workflow.md):
- precio < min_price → BLOCKING (vender por debajo del mínimo)
- precio >= min_price → OK
- referencia desconocida en catálogo → WARNING (registrar para revisión)
- min_price no definido en el catálogo → WARNING (catálogo incompleto)

El resultado se inyecta en `extracted_json["validation"]` con la forma:
    {
        "summary": {"blocking": int, "warnings": int, "ok": int, "unknown": int},
        "lines": [
            {"line_index": 0, "reference": "TF-75", "level": "ok|warning|blocking",
             "message": "...", "min_price": 12.5, "actual_price": 15.0}
        ]
    }
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.logging import get_logger
from app.models.catalog_item import CatalogItem, normalize_reference

log = get_logger(__name__)

LEVEL_OK = "ok"
LEVEL_WARNING = "warning"
LEVEL_BLOCKING = "blocking"
LEVEL_UNKNOWN = "unknown"


def validate_against_catalog(
    extracted_json: dict[str, Any],
    catalog: list[CatalogItem],
) -> dict[str, Any]:
    """Devuelve un bloque de validación. NO modifica `extracted_json`."""
    by_ref = {item.reference_normalized: item for item in catalog if item.active}

    lineas = extracted_json.get("lineas", []) or []
    line_results: list[dict[str, Any]] = []
    blocking = warnings = ok = unknown = 0

    for i, linea in enumerate(lineas):
        if not isinstance(linea, dict):
            continue
        ref = linea.get("referencia")
        precio = linea.get("precio_unitario")

        result: dict[str, Any] = {
            "line_index": i,
            "reference": ref,
            "actual_price": precio,
            "level": LEVEL_UNKNOWN,
            "message": "",
            "min_price": None,
        }

        if not ref:
            result["level"] = LEVEL_WARNING
            result["message"] = "Línea sin referencia detectada"
            warnings += 1
            line_results.append(result)
            continue

        norm = normalize_reference(ref)
        item = by_ref.get(norm)

        if item is None:
            result["level"] = LEVEL_UNKNOWN
            result["message"] = f"Referencia '{ref}' no está en el catálogo"
            unknown += 1
            line_results.append(result)
            continue

        result["min_price"] = float(item.min_price) if item.min_price is not None else None

        if item.min_price is None:
            result["level"] = LEVEL_WARNING
            result["message"] = f"'{ref}' sin precio mínimo definido en el catálogo"
            warnings += 1
            line_results.append(result)
            continue

        if precio is None:
            result["level"] = LEVEL_WARNING
            result["message"] = f"'{ref}' sin precio en el pedido"
            warnings += 1
            line_results.append(result)
            continue

        try:
            actual = Decimal(str(precio))
        except Exception:
            result["level"] = LEVEL_WARNING
            result["message"] = f"Precio no numérico ('{precio}')"
            warnings += 1
            line_results.append(result)
            continue

        if actual < item.min_price:
            result["level"] = LEVEL_BLOCKING
            diff = item.min_price - actual
            result["message"] = (
                f"Precio {actual} < mínimo {item.min_price} ({item.currency}). "
                f"Diferencia: -{diff}"
            )
            blocking += 1
        else:
            result["level"] = LEVEL_OK
            ok += 1

        line_results.append(result)

    summary = {
        "blocking": blocking,
        "warnings": warnings,
        "ok": ok,
        "unknown": unknown,
        "total_lines": len(line_results),
    }
    return {"summary": summary, "lines": line_results}
