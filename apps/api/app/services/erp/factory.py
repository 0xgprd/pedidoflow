"""Factory que devuelve el `ERPAdapter` configurado para el tenant.

Hoy lee de `app.core.config.settings` (config global). Cuando entre el modelo
`TenantERPConfig` (uno por tenant con credenciales encriptadas), esta función
recibirá el `tenant_id` y devolverá el adapter configurado para ese tenant.

Uso:
    adapter = get_erp_adapter()
    if adapter is None:
        raise HTTPException(503, "ERP no configurado para este tenant")
    result = adapter.push_sales_order(canonical_order)
"""

from __future__ import annotations

from app.core.config import settings
from app.services.erp.adapter import ERPAdapter
from app.services.erp.erpnext import ERPNextAdapter, ERPNextConfig


def get_erp_adapter() -> ERPAdapter | None:
    """Devuelve el adapter configurado o None si no hay ERP configurado.

    Por ahora solo soporta ERPNext (read from settings.erpnext_*).
    Para añadir Sage/Holded/CSV: leer un campo de discriminador del settings
    o de TenantERPConfig y devolver el adapter correspondiente.
    """
    if settings.erpnext_base_url and settings.erpnext_api_key:
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
        return ERPNextAdapter(cfg)
    return None
