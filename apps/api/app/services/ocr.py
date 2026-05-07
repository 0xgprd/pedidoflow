"""OCR service — convierte PDF en markdown estructurado.

Provider por defecto: Mistral OCR (https://docs.mistral.ai/capabilities/document/).
Encapsulado en `OCRProvider` para poder cambiar a Google Document AI / AWS Textract
en el futuro sin tocar el resto del pipeline.
"""

from __future__ import annotations

import base64
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


class OCRPage(BaseModel):
    """Una página del documento tras OCR."""

    index: int
    markdown: str
    width: float | None = None
    height: float | None = None


class OCRResult(BaseModel):
    """Resultado completo del OCR sobre un PDF."""

    pages: list[OCRPage] = Field(default_factory=list)
    model: str | None = None
    pages_processed: int | None = None
    raw: dict[str, Any] | None = None  # respuesta cruda del provider para debugging

    @property
    def full_markdown(self) -> str:
        """Concatena todas las páginas separadas por marcador, conservando orden."""
        return "\n\n---PAGE---\n\n".join(p.markdown for p in self.pages)


class OCRError(Exception):
    """Error no recuperable del OCR (4xx, parseo, schema)."""


class OCRProvider(Protocol):
    def extract(self, pdf_bytes: bytes) -> OCRResult: ...


# =============================================================================
# Mistral OCR
# =============================================================================


class MistralOCRProvider:
    """Cliente Mistral OCR.

    Endpoint: POST https://api.mistral.ai/v1/ocr
    Auth: Bearer <api_key>
    Pricing: ~$1 / 1000 páginas.
    """

    BASE_URL = "https://api.mistral.ai/v1/ocr"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.api_key = api_key or settings.mistral_api_key
        self.model = model or settings.mistral_ocr_model
        self.timeout = timeout
        if not self.api_key:
            raise OCRError("MISTRAL_API_KEY no configurada")

    def extract(self, pdf_bytes: bytes) -> OCRResult:
        b64 = base64.standard_b64encode(pdf_bytes).decode("ascii")
        payload = {
            "model": self.model,
            "document": {
                "type": "document_url",
                "document_url": f"data:application/pdf;base64,{b64}",
            },
            "include_image_base64": False,
        }

        log.info("ocr.mistral.start", bytes=len(pdf_bytes), model=self.model)

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    self.BASE_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.HTTPError as e:
            log.error("ocr.mistral.http_error", error=str(e))
            raise OCRError(f"Mistral OCR HTTP error: {e}") from e

        if resp.status_code >= 400:
            log.error("ocr.mistral.api_error", status=resp.status_code, body=resp.text[:500])
            raise OCRError(f"Mistral OCR API {resp.status_code}: {resp.text[:200]}")

        try:
            data = resp.json()
        except ValueError as e:
            raise OCRError(f"Mistral OCR returned non-JSON: {e}") from e

        return self._parse(data)

    @staticmethod
    def _parse(data: dict[str, Any]) -> OCRResult:
        raw_pages = data.get("pages") or []
        pages: list[OCRPage] = []
        for p in raw_pages:
            dims = p.get("dimensions") or {}
            pages.append(
                OCRPage(
                    index=p.get("index", 0),
                    markdown=p.get("markdown", ""),
                    width=dims.get("width"),
                    height=dims.get("height"),
                )
            )

        usage = data.get("usage_info") or {}
        result = OCRResult(
            pages=pages,
            model=data.get("model"),
            pages_processed=usage.get("pages_processed") or len(pages),
            raw=data,
        )
        log.info(
            "ocr.mistral.ok",
            pages=len(pages),
            chars=sum(len(p.markdown) for p in pages),
        )
        return result


# =============================================================================
# Singleton
# =============================================================================

_provider_singleton: OCRProvider | None = None


def get_ocr_provider() -> OCRProvider:
    """Devuelve el provider OCR configurado (singleton)."""
    global _provider_singleton
    if _provider_singleton is None:
        _provider_singleton = MistralOCRProvider()
    return _provider_singleton


def set_ocr_provider(provider: OCRProvider | None) -> None:
    """Para tests — inyecta un provider stub o resetea el singleton."""
    global _provider_singleton
    _provider_singleton = provider
