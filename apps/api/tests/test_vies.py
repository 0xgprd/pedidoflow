"""Tests del verificador VIES (sin red real — httpx.MockTransport)."""

from __future__ import annotations

import httpx

from app.services.vies import _split_vat, verify_eu_vat

# =============================================================================
# Parser de VAT
# =============================================================================


def test_split_vat_accepts_clean() -> None:
    assert _split_vat("FR76344020383") == ("FR", "76344020383")
    assert _split_vat("ESB12345678") == ("ES", "B12345678")


def test_split_vat_accepts_with_spaces_and_dashes() -> None:
    assert _split_vat("FR 76 344-020/383") == ("FR", "76344020383")
    assert _split_vat("ES-B12345678") == ("ES", "B12345678")


def test_split_vat_lowercase_normalized() -> None:
    assert _split_vat("fr76344020383") == ("FR", "76344020383")


def test_split_vat_invalid_returns_none() -> None:
    assert _split_vat("123456") is None  # sin código país
    assert _split_vat("") is None
    # El parser es laxo: acepta cualquier 2 letras + alfanumérico. La validación
    # de país UE y la validez del número la hace VIES. Aquí solo separamos.
    assert _split_vat("FR") is None  # 2 letras, sin número


# =============================================================================
# verify_eu_vat — happy path
# =============================================================================


def test_verify_returns_valid_when_vies_says_yes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/FR/vat/76344020383")
        return httpx.Response(
            200,
            json={
                "isValid": True,
                "name": "ACME France SAS",
                "address": "12 Rue de Test\n75001 Paris\nFRANCE",
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    result = verify_eu_vat("FR76344020383", client=client)

    assert result.valid is True
    assert result.country_code == "FR"
    assert result.vat_number == "76344020383"
    assert result.name == "ACME France SAS"
    assert result.address is not None
    assert "Paris" in result.address
    assert result.error is None


def test_verify_returns_invalid_when_vies_says_no() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"isValid": False})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    result = verify_eu_vat("FR99999999999", client=client)

    assert result.valid is False
    assert result.error is None
    assert result.name is None


def test_verify_filters_dashes_in_response() -> None:
    """VIES devuelve '---' cuando el operador oculta nombre/dirección."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"isValid": True, "name": "---", "address": "---"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = verify_eu_vat("FR76344020383", client=client)

    assert result.valid is True
    assert result.name is None
    assert result.address is None


# =============================================================================
# Errores y casos límite
# =============================================================================


def test_verify_invalid_format_returns_false_with_error() -> None:
    result = verify_eu_vat("123-no-vat")
    assert result.valid is False
    assert result.error is not None
    assert "formato" in result.error.lower()


def test_verify_non_eu_country_returns_false_with_error() -> None:
    result = verify_eu_vat("US123456789")
    assert result.valid is False
    assert result.error is not None
    assert "no es UE" in result.error


def test_verify_uk_after_brexit_is_not_eu() -> None:
    """GB ya no es UE; VIES no aplica."""
    result = verify_eu_vat("GB123456789")
    assert result.valid is False
    assert "no es UE" in (result.error or "")


def test_verify_xi_northern_ireland_is_eu() -> None:
    """XI (Irlanda del Norte) sigue siendo VIES tras Brexit."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/XI/vat/" in request.url.path
        return httpx.Response(200, json={"isValid": True, "name": "ACME NI Ltd"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = verify_eu_vat("XI123456789", client=client)
    assert result.valid is True


def test_verify_returns_none_on_timeout() -> None:
    """Timeout → valid=None (no determinable). El caller decide."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = verify_eu_vat("FR76344020383", client=client)
    assert result.valid is None
    assert result.error is not None
    assert "VIES" in result.error


def test_verify_returns_none_on_5xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="overloaded")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = verify_eu_vat("FR76344020383", client=client)
    assert result.valid is None
    assert "503" in (result.error or "")


def test_verify_returns_none_on_non_json_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>maintenance</html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = verify_eu_vat("FR76344020383", client=client)
    assert result.valid is None
    assert "JSON" in (result.error or "")
