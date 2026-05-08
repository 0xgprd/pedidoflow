"""Validación VIES — VAT intracomunitarios contra la Comisión Europea.

VIES (VAT Information Exchange System) es la base oficial de la Comisión
Europea. Cuando una empresa española factura a otro país UE con IVA 0%
(inversión del sujeto pasivo), Hacienda exige que el VAT del cliente esté
validado contra VIES en el momento de la operación. Si no, te reclama
el IVA.

Este módulo expone una función simple:
    `verify_eu_vat(vat: str) -> ViesResult`

Devuelve si el VAT es válido, el nombre y dirección registrados (cuando
están disponibles) y un sello de tiempo de la consulta.

API usada: REST de la Comisión Europea (gratuito, sin auth).
    https://ec.europa.eu/taxation_customs/vies/rest-api/

Servicio público y a veces lento — usamos timeout corto y, si falla, el
resultado es `valid=None` (desconocido). Eso permite al caller distinguir
"VAT inválido" de "VIES no respondió".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)

VIES_API_URL = "https://ec.europa.eu/taxation_customs/vies/rest-api/ms/{country}/vat/{number}"

# Códigos país aceptados por VIES (UE-27 + EL para Grecia + XI para Irlanda Norte
# tras Brexit; GB ya no es UE).
VIES_COUNTRIES = frozenset(
    {
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
        "XI",
    }
)

_VAT_PATTERN = re.compile(r"^([A-Z]{2})([0-9A-Z]+)$")


@dataclass(frozen=True)
class ViesResult:
    """Resultado de validar un VAT contra VIES.

    - `valid`: True/False/None. None = no se pudo determinar (timeout, 5xx).
    - `name`: razón social registrada (si VIES la devolvió y `valid=True`).
    - `address`: dirección registrada (puede venir multilínea con \\n).
    - `country_code`: código país que se usó en la consulta.
    - `vat_number`: número (sin código país).
    - `checked_at`: timestamp UTC de la consulta.
    - `error`: detalle si valid is None.
    """

    valid: bool | None
    country_code: str
    vat_number: str
    name: str | None = None
    address: str | None = None
    checked_at: datetime = datetime.now(UTC)
    error: str | None = None


def _split_vat(raw: str) -> tuple[str, str] | None:
    """Separa 'FR76344020383' → ('FR', '76344020383'). Acepta espacios y guiones."""
    cleaned = re.sub(r"[\s\-./]", "", raw or "").upper()
    m = _VAT_PATTERN.match(cleaned)
    if not m:
        return None
    return m.group(1), m.group(2)


def verify_eu_vat(
    vat: str,
    *,
    timeout_seconds: float = 5.0,
    client: httpx.Client | None = None,
) -> ViesResult:
    """Valida `vat` contra la base VIES de la Comisión Europea.

    `vat` puede venir con o sin espacios/guiones (e.g. "FR 76 344020383").
    Devuelve `ViesResult.valid is None` si la API no responde — que el
    caller decida si bloquear o avisar.

    Para tests, pasar `client` con httpx.MockTransport.
    """
    parts = _split_vat(vat)
    if parts is None:
        return ViesResult(
            valid=False,
            country_code="",
            vat_number=vat,
            error="VAT no tiene formato válido (esperado: 2 letras país + número)",
        )
    country, number = parts
    if country not in VIES_COUNTRIES:
        return ViesResult(
            valid=False,
            country_code=country,
            vat_number=number,
            error=f"País '{country}' no es UE — VIES no aplica",
        )

    url = VIES_API_URL.format(country=country, number=number)

    owns_client = client is None
    http = client or httpx.Client(timeout=timeout_seconds)
    try:
        try:
            response = http.get(url)
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            log.warning("vies.network_error", vat=vat, error=str(e))
            return ViesResult(
                valid=None,
                country_code=country,
                vat_number=number,
                error=f"VIES no respondió: {e}",
            )

        if response.status_code != 200:
            log.warning("vies.http_error", status=response.status_code, vat=vat)
            return ViesResult(
                valid=None,
                country_code=country,
                vat_number=number,
                error=f"VIES devolvió HTTP {response.status_code}",
            )

        try:
            data = response.json()
        except ValueError as e:
            return ViesResult(
                valid=None,
                country_code=country,
                vat_number=number,
                error=f"VIES devolvió respuesta no JSON: {e}",
            )

        # Estructura típica de VIES REST:
        # { "isValid": true, "name": "ACME SA", "address": "Calle X\n12345 Madrid", ... }
        is_valid = bool(data.get("isValid"))
        name = data.get("name") or None
        address = data.get("address") or None
        # VIES devuelve "---" o vacío cuando el operador no quiere exponer el dato
        if name in ("---", ""):
            name = None
        if address in ("---", ""):
            address = None

        log.info("vies.checked", vat=vat, valid=is_valid)
        return ViesResult(
            valid=is_valid,
            country_code=country,
            vat_number=number,
            name=name,
            address=address,
        )
    finally:
        if owns_client:
            http.close()
