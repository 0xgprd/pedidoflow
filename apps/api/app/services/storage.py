"""Storage de PDFs.

Estrategia:
- Producción: Cloudflare R2 (S3-compatible) via boto3.
- Dev local sin credenciales: filesystem `./storage_local/{tenant_id}/{uuid}.pdf`.

El backend se elige según presencia de `S3_ACCESS_KEY_ID` en settings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


class StorageBackend(Protocol):
    def upload_pdf(
        self,
        *,
        tenant_id: UUID,
        object_id: UUID,
        body: bytes,
        original_filename: str | None = None,
    ) -> str: ...

    def download_pdf(self, key: str) -> bytes: ...

    def presigned_url(self, key: str, expires_in: int = 3600) -> str: ...


class LocalStorageBackend:
    """Guarda en disco local. Solo dev — los archivos NO son servidos por la API."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / key

    def upload_pdf(
        self,
        *,
        tenant_id: UUID,
        object_id: UUID,
        body: bytes,
        original_filename: str | None = None,
    ) -> str:
        key = f"{tenant_id}/{object_id}.pdf"
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        log.info("storage.local.uploaded", key=key, bytes=len(body))
        return key

    def download_pdf(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        # En local no hay URL pública — devolvemos pseudo-URL para debugging.
        return f"file://{self._path(key).resolve()}"


class S3StorageBackend:
    """Cloudflare R2 (o cualquier S3) via boto3."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        region: str,
    ) -> None:
        import boto3

        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
        )

    def upload_pdf(
        self,
        *,
        tenant_id: UUID,
        object_id: UUID,
        body: bytes,
        original_filename: str | None = None,
    ) -> str:
        key = f"{tenant_id}/{object_id}.pdf"
        extra = {"ContentType": "application/pdf"}
        if original_filename:
            extra["ContentDisposition"] = f'inline; filename="{original_filename}"'
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body, **extra)
        log.info("storage.s3.uploaded", key=key, bytes=len(body))
        return key

    def download_pdf(self, key: str) -> bytes:
        resp = self.client.get_object(Bucket=self.bucket, Key=key)
        return resp["Body"].read()

    def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )


_storage_singleton: StorageBackend | None = None


def get_storage_service() -> StorageBackend:
    """Devuelve el backend de storage configurado (singleton)."""
    global _storage_singleton
    if _storage_singleton is not None:
        return _storage_singleton

    if settings.s3_access_key_id and settings.s3_endpoint_url:
        _storage_singleton = S3StorageBackend(
            endpoint_url=settings.s3_endpoint_url,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
            bucket=settings.s3_bucket,
            region=settings.s3_region,
        )
        log.info("storage.backend.s3", bucket=settings.s3_bucket)
    else:
        # Raíz del repo / storage_local en local. En Docker (Railway) no hay
        # 4 niveles arriba — usamos /tmp/storage_local como fallback.
        parents = Path(__file__).resolve().parents
        root = parents[4] / "storage_local" if len(parents) > 4 else Path("/tmp/storage_local")
        _storage_singleton = LocalStorageBackend(root=root)
        log.info("storage.backend.local", root=str(root))

    return _storage_singleton


def reset_storage_service() -> None:
    """Para tests — reinicia el singleton."""
    global _storage_singleton
    _storage_singleton = None
