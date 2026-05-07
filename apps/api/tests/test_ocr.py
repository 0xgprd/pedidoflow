"""Tests del OCRProvider (parsing de respuestas Mistral, sin llamada real)."""

import pytest

from app.services.ocr import MistralOCRProvider, OCRError, OCRResult


def test_parse_basic_response() -> None:
    data = {
        "model": "mistral-ocr-2501",
        "pages": [
            {
                "index": 0,
                "markdown": "# Pedido 12345\n\n| Ref | Cant |\n|---|---|\n| TF-75 | 10 |",
                "dimensions": {"width": 1700, "height": 2200, "dpi": 200},
            },
            {
                "index": 1,
                "markdown": "Total: 125.00 €",
                "dimensions": {"width": 1700, "height": 2200},
            },
        ],
        "usage_info": {"pages_processed": 2},
    }
    result = MistralOCRProvider._parse(data)
    assert isinstance(result, OCRResult)
    assert len(result.pages) == 2
    assert result.pages[0].index == 0
    assert "TF-75" in result.pages[0].markdown
    assert result.pages[0].width == 1700
    assert result.model == "mistral-ocr-2501"
    assert result.pages_processed == 2
    # full_markdown concatena con separador
    assert "---PAGE---" in result.full_markdown
    assert "TF-75" in result.full_markdown
    assert "Total: 125.00" in result.full_markdown


def test_parse_empty_pages() -> None:
    data = {"pages": [], "model": "mistral-ocr-latest"}
    result = MistralOCRProvider._parse(data)
    assert result.pages == []
    assert result.full_markdown == ""


def test_parse_missing_dimensions() -> None:
    data = {"pages": [{"index": 0, "markdown": "hola"}]}
    result = MistralOCRProvider._parse(data)
    assert result.pages[0].width is None
    assert result.pages[0].height is None


def test_init_without_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import ocr as ocr_module

    monkeypatch.setattr(ocr_module.settings, "mistral_api_key", "")
    with pytest.raises(OCRError, match="MISTRAL_API_KEY no configurada"):
        MistralOCRProvider()
