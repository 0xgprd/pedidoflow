"""Smoke test: empuja un pedido Quimilock real a la instancia ERPNext local.

Uso:
    cd apps/api
    .venv\\Scripts\\python.exe scripts/smoke_erpnext_push.py

Lee credenciales de las env vars ERPNEXT_* (definidas en .env de la raíz).
Si la instancia no responde, sale con error claro.
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

# Asegura que apps/api esté en sys.path cuando se ejecuta como script
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Windows: la consola usa cp1252 por defecto y peta con flechas/símbolos UTF-8.
# Reconfiguramos stdout/stderr a UTF-8 si es posible.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from app.core.config import settings  # noqa: E402
from app.services.erp.canonical import (  # noqa: E402
    CanonicalCustomer,
    CanonicalLine,
    CanonicalSalesOrder,
)
from app.services.erp.erpnext import ERPNextAdapter, ERPNextConfig  # noqa: E402


def _quimilock_cf26072() -> CanonicalSalesOrder:
    """Pedido real CF26072 — ATS / Quimilock TL260420-213M1."""
    return CanonicalSalesOrder(
        source_document_id=uuid4(),
        customer_po_number="CF26072",
        quotation_reference="TL260420-213M1",
        customer=CanonicalCustomer(
            name="ATS",
            tax_id=None,
            eu_vat="FR76344020383",
            email="accueil@angouleme-ts.fr",
            shipping_address="Z.I. Des Agriers, 16000 Angouleme, France",
            billing_address="Z.I. Des Agriers, 16000 Angouleme, France",
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
            CanonicalLine(
                reference="TR-400",
                description="TR-400",
                quantity=Decimal("20"),
                unit_price=Decimal("39.795"),
                line_amount=Decimal("795.9"),
            ),
        ],
        subtotal_amount=Decimal("1257.4"),
        shipping_amount=Decimal("289.58"),
        tax_amount=None,
        total_amount=Decimal("1546.98"),
        notes="Transport: FRANCO. Conditions de réglement: Vírement au 30/06/26.",
    )


def main() -> int:
    if not settings.erpnext_base_url:
        print("ERPNEXT_BASE_URL no está en el entorno. Configura .env.", file=sys.stderr)
        return 2

    cfg = ERPNextConfig(
        base_url=settings.erpnext_base_url,
        api_key=settings.erpnext_api_key,
        api_secret=settings.erpnext_api_secret,
        default_company=settings.erpnext_default_company,
        default_currency=settings.erpnext_default_currency,
        default_customer_group=settings.erpnext_default_customer_group,
        default_territory=settings.erpnext_default_territory,
        default_item_group=settings.erpnext_default_item_group,
        default_stock_uom=settings.erpnext_default_stock_uom,
        timeout_seconds=settings.erpnext_timeout_seconds,
    )
    adapter = ERPNextAdapter(cfg)

    print(f"→ Health check {cfg.base_url} ... ", end="", flush=True)
    if not adapter.health_check():
        print("FAIL")
        print("  No respondió pong. Comprueba que el stack está arriba:")
        print("  cd ../erpnext-sandbox && docker compose -f pwd.yml up -d")
        return 1
    print("OK")

    order = _quimilock_cf26072()
    print(
        f"→ Pushing Sales Order: customer={order.customer.name} po={order.customer_po_number} ..."
    )
    try:
        result = adapter.push_sales_order(order)
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print()
    print("=" * 60)
    print(f"  Sales Order creado: {result.erp_id}")
    print(f"  Status:              {result.status}")
    print(f"  URL:                 {result.erp_url}")
    if result.warnings:
        print("  Warnings:")
        for w in result.warnings:
            print(f"    - {w}")
    print("=" * 60)
    print()
    print(f"  Verifícalo en: {cfg.base_url}/app/sales-order")
    return 0


if __name__ == "__main__":
    sys.exit(main())
