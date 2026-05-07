"""Conexión a Postgres + sesiones SQLModel."""

from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    echo=settings.database_echo,
    # pool_pre_ping añade un SELECT 1 a cada checkout — útil contra conexiones
    # huérfanas pero penaliza ~100-200ms por request en latencia alta (Supabase
    # EU desde España). Lo dejamos OFF y reciclamos cada 30 min.
    pool_pre_ping=False,
    pool_recycle=1800,
    pool_size=10,
    max_overflow=20,
)


def init_db() -> None:
    """Crea tablas (solo dev). En prod usar Alembic."""
    # Importar modelos para que SQLModel los registre.
    # noqa porque solo queremos el side-effect del import.
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """Dependency injection FastAPI para session DB."""
    with Session(engine) as session:
        yield session
