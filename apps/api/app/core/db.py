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
    """Bootstrap inicial — solo si la DB está vacía.

    En cuanto haya alguna tabla nuestra, NO toca nada (las migraciones reales
    se aplican via `alembic upgrade head`). Esto evita que `create_all` cree
    índices/constraints inconsistentes con los que Alembic gestiona.
    """
    from sqlalchemy import inspect

    # Importar modelos para que SQLModel los registre (side-effect).
    from app import models  # noqa: F401

    insp = inspect(engine)
    existing = set(insp.get_table_names())
    # Si ya hay tablas nuestras, asumimos schema gestionado por Alembic.
    our_tables = {t.name for t in SQLModel.metadata.tables.values()}
    if existing & our_tables:
        return

    # Schema vacío → bootstrap inicial (útil en tests y primer deploy)
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """Dependency injection FastAPI para session DB."""
    with Session(engine) as session:
        yield session
