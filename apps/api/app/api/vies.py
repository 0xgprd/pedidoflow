"""Endpoint público de verificación VIES — la UI lo llama mientras el usuario
edita una ficha de alta para mostrarle el resultado en vivo.

Wraps la función `services/vies.py`. Sin tenant check (son datos públicos
de la Comisión Europea, no hay PII del tenant).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.services.vies import ViesResult, verify_eu_vat

router = APIRouter(prefix="/vies", tags=["vies"])


class ViesVerifyResponse(BaseModel):
    valid: bool | None
    country_code: str
    vat_number: str
    name: str | None = None
    address: str | None = None
    error: str | None = None


def _to_response(r: ViesResult) -> ViesVerifyResponse:
    return ViesVerifyResponse(
        valid=r.valid,
        country_code=r.country_code,
        vat_number=r.vat_number,
        name=r.name,
        address=r.address,
        error=r.error,
    )


@router.get("/verify", response_model=ViesVerifyResponse)
def verify_vat(
    vat: Annotated[str, Query(min_length=1, max_length=30)],
) -> ViesVerifyResponse:
    """Verifica un VAT intracomunitario contra VIES.

    `valid=null` significa que VIES no respondió (timeout, 5xx) — la UI
    debería tratarlo como "desconocido", no como inválido. La UI puede
    reintentar manualmente.
    """
    return _to_response(verify_eu_vat(vat))
