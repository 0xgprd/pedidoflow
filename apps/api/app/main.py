"""Entrypoint FastAPI.

Run en local:
    uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.router import api_router
from app.core.config import settings
from app.core.db import init_db
from app.core.logging import configure_logging, get_logger

configure_logging(debug=settings.app_debug)
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks."""
    import asyncio

    log.info("app.startup", env=settings.app_env, version=__version__)
    if settings.app_env == "development":
        # En dev creamos tablas si no existen. En prod usar Alembic.
        # Con timeout corto: si Postgres no responde, app arranca igual.
        try:
            await asyncio.wait_for(asyncio.to_thread(init_db), timeout=5.0)
            log.info("db.init.ok")
        except TimeoutError:
            log.warning("db.init.timeout", hint="¿Postgres arrancado? `docker compose up -d`")
        except Exception as e:
            log.warning("db.init.failed", error=str(e))
    yield
    log.info("app.shutdown")


app = FastAPI(
    title="Order Flow API",
    description="SaaS de automatización de pedidos para Sage 200 y otros ERPs.",
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {
        "name": "Order Flow API",
        "version": __version__,
        "env": settings.app_env,
        "docs": "/docs",
    }
