"""Tests del parsing del ExtractionService (sin llamada real a Anthropic)."""

import pytest

from app.services.extraction import ExtractionError, ExtractionService


def test_parse_clean_json() -> None:
    raw = """{
      "cliente": {"nombre": "Ebolis", "cif_nif": "B12345678"},
      "pedido": {"numero_oferta": "TL250506-1", "fecha_pedido": "2026-05-06"},
      "lineas": [
        {"referencia": "TF-75", "descripcion": "Tubo flexible 75", "cantidad": 10, "unidad": "ML", "precio_unitario": 12.5}
      ],
      "totales": {"subtotal_ht": 125.0},
      "confianza_global": "alta",
      "source_texts": {
        "cliente.nombre": "Cliente: Ebolis SAS",
        "lineas.0.referencia": "TF-75 Tubo flexible 75 mm"
      }
    }"""
    result = ExtractionService._parse(raw)
    assert result.cliente.nombre == "Ebolis"
    assert result.pedido.numero_oferta == "TL250506-1"
    assert len(result.lineas) == 1
    assert result.lineas[0].referencia == "TF-75"
    assert result.lineas[0].cantidad == 10
    assert result.confianza_global == "alta"
    assert result.source_texts["cliente.nombre"] == "Cliente: Ebolis SAS"
    assert result.source_texts["lineas.0.referencia"] == "TF-75 Tubo flexible 75 mm"


def test_parse_strips_markdown_fences() -> None:
    raw = '```json\n{"lineas": [], "confianza_global": "media", "source_texts": {}}\n```'
    result = ExtractionService._parse(raw)
    assert result.lineas == []


def test_parse_invalid_json_raises() -> None:
    with pytest.raises(ExtractionError):
        ExtractionService._parse("not a json at all")


def test_parse_minimal_payload() -> None:
    """Sin source_texts (campo opcional con default)."""
    raw = '{"lineas": [], "confianza_global": "baja"}'
    result = ExtractionService._parse(raw)
    assert result.cliente.nombre is None
    assert result.lineas == []
    assert result.source_texts == {}


def test_extract_rejects_empty_markdown() -> None:
    """Si el OCR no produjo nada, no llamamos a Claude."""
    service = ExtractionService(api_key="sk-fake")
    with pytest.raises(ExtractionError, match="Markdown vacío"):
        service.extract("   \n  ")
