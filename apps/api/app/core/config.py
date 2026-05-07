"""Configuración centralizada via pydantic-settings.

Lee variables de entorno del fichero .env (en la raíz del repo).
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# El .env vive en la raíz del monorepo (4 niveles arriba: app/core/config.py -> apps/api/app/core/)
_ENV_FILE = Path(__file__).resolve().parents[4] / ".env"


class Settings(BaseSettings):
    """Settings de la aplicación. Tipado fuerte, fail-fast en startup."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App ---
    app_env: str = Field(default="development")
    app_debug: bool = Field(default=True)
    app_secret_key: str = Field(default="dev-secret-change-me")

    # --- Database ---
    database_url: str = Field(
        default="postgresql+psycopg://pedidoflow:pedidoflow@localhost:5432/pedidoflow"
    )
    database_echo: bool = Field(default=False)

    # --- Redis / Celery ---
    redis_url: str = Field(default="redis://localhost:6379/0")
    celery_broker_url: str = Field(default="redis://localhost:6379/1")
    celery_result_backend: str = Field(default="redis://localhost:6379/2")
    celery_task_always_eager: bool = Field(default=False)

    # --- Auth (Clerk) ---
    clerk_publishable_key: str = Field(default="")
    clerk_secret_key: str = Field(default="")
    clerk_jwt_issuer: str = Field(default="")

    # --- IA ---
    anthropic_api_key: str = Field(default="")
    anthropic_model: str = Field(default="claude-sonnet-4-6")
    voyage_api_key: str = Field(default="")
    voyage_model: str = Field(default="voyage-3")

    # --- OCR ---
    mistral_api_key: str = Field(default="")
    mistral_ocr_model: str = Field(default="mistral-ocr-latest")

    # --- Storage ---
    s3_endpoint_url: str = Field(default="")
    s3_access_key_id: str = Field(default="")
    s3_secret_access_key: str = Field(default="")
    s3_bucket: str = Field(default="pedidoflow-documents")
    s3_region: str = Field(default="auto")

    # --- Microsoft Graph (Outlook integration) ---
    # Para apps multi-tenant usar "common" o "consumers"; para single-tenant tu Tenant ID
    ms_graph_tenant_id: str = Field(default="common")
    ms_graph_client_id: str = Field(default="")
    ms_graph_client_secret: str = Field(default="")
    ms_graph_redirect_uri: str = Field(
        default="http://localhost:8000/api/v1/integrations/outlook/callback"
    )
    # Scopes que pediremos: leer correos + offline_access para refresh tokens
    ms_graph_scopes: str = Field(default="Mail.Read offline_access User.Read")
    # URL del frontend para redirigir tras callback exitoso/fallido
    ms_graph_post_callback_url: str = Field(default="http://localhost:5173/integrations")

    # --- Sage 200 ---
    sage200_base_url: str = Field(default="https://sage200.sage.es/api/sales")
    sage200_api_version: str = Field(default="1.0")
    sage200_oauth_client_id: str = Field(default="")
    sage200_oauth_client_secret: str = Field(default="")
    sage200_oauth_token_url: str = Field(default="")
    sage200_subscription_key: str = Field(default="")
    sage200_x_site: str = Field(default="")

    # --- Observability ---
    sentry_dsn: str = Field(default="")
    logfire_token: str = Field(default="")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def cors_origins(self) -> list[str]:
        if self.is_production:
            return []  # configurar dominios reales en prod
        return [
            "http://localhost:5173",  # Vite dev
            "http://localhost:3000",
            "http://127.0.0.1:5173",
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings (cached)."""
    return Settings()


settings = get_settings()
