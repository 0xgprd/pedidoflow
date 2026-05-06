"""Endpoints de salud / liveness."""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlmodel import Session

from app import __version__
from app.core.db import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Liveness simple — siempre 200 si el proceso está vivo."""
    return {
        "status": "ok",
        "version": __version__,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health/ready")
def ready(session: Annotated[Session, Depends(get_session)]) -> dict:
    """Readiness — comprueba que la DB responde."""
    db_ok = False
    pgvector_ok = False
    try:
        session.exec(text("SELECT 1"))  # type: ignore[call-overload]
        db_ok = True
        result = session.exec(  # type: ignore[call-overload]
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        ).first()
        pgvector_ok = result is not None
    except Exception:
        pass

    status = "ok" if db_ok and pgvector_ok else "degraded"
    return {
        "status": status,
        "checks": {
            "database": db_ok,
            "pgvector": pgvector_ok,
        },
    }
