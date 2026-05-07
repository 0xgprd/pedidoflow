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


def test_prompt_prefers_vendor_ref_over_customer_ref() -> None:
    """Regresión 2026-05-07: en pedidos con doble código por línea (Customer PN +
    Vendor PN), Claude empezó a extraer la del cliente. El prompt ahora obliga a
    priorizar la del proveedor. Test asegura que la instrucción sigue presente."""
    from app.services.extraction import SYSTEM_PROMPT

    p = SYSTEM_PROMPT
    assert "DOS códigos" in p
    assert "PROVEEDOR" in p or "VENDOR" in p
    assert "Ref interne" in p or "Ref Interne" in p
    # El ejemplo concreto sigue documentado
    assert "GE000002" in p and "DEB-01" in p


def test_parse_includes_new_fixed_fields() -> None:
    """Los nuevos campos fijos (numero_iva, direccion_facturacion, transporte) parsean OK."""
    raw = """{
      "cliente": {
        "nombre": "ACME",
        "cif_nif": "B12345678",
        "numero_iva": "ESB12345678",
        "direccion_entrega": "C/ Falsa 1",
        "direccion_facturacion": "C/ Real 2"
      },
      "totales": {"subtotal_ht": 1500.0, "transporte": 75.0, "total_ttc": 1815.0},
      "lineas": [],
      "confianza_global": "alta"
    }"""
    result = ExtractionService._parse(raw)
    assert result.cliente.numero_iva == "ESB12345678"
    assert result.cliente.direccion_facturacion == "C/ Real 2"
    assert result.totales.transporte == 75.0


def test_parse_custom_block() -> None:
    """El bloque `custom` (campos del tenant) parsea como dict."""
    raw = """{
      "lineas": [],
      "confianza_global": "media",
      "custom": {"horario_de_entrega": "10h-13h", "incoterm": null}
    }"""
    result = ExtractionService._parse(raw)
    assert result.custom == {"horario_de_entrega": "10h-13h", "incoterm": None}


def test_extract_builds_custom_field_specs_block(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica que custom_field_specs se inyecta como system block."""
    captured: dict = {}

    class FakeUsage:
        input_tokens = 10
        output_tokens = 20
        cache_read_input_tokens = 0
        cache_creation_input_tokens = 0

    class FakeBlock:
        type = "text"
        text = '{"lineas": [], "confianza_global": "media"}'

    class FakeResponse:
        content = [FakeBlock()]
        usage = FakeUsage()

    class FakeMessages:
        def create(self, **kwargs):
            captured["system"] = kwargs.get("system")
            return FakeResponse()

    class FakeClient:
        def __init__(self, **_):
            self.messages = FakeMessages()

    monkeypatch.setattr("anthropic.Anthropic", FakeClient)

    service = ExtractionService(api_key="sk-fake")
    service.extract(
        "markdown content",
        custom_field_specs=[
            ("horario_de_entrega", "Horario de entrega", None),
            ("incoterm", "Incoterm", "FCA, DAP, etc."),
        ],
    )

    system_texts = "\n".join(b["text"] for b in captured["system"])
    assert "horario_de_entrega" in system_texts
    assert "Horario de entrega" in system_texts
    assert "FCA, DAP" in system_texts
