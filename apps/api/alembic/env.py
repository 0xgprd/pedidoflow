"""Alembic env.py — configurado para SQLModel + settings de Order Flow.

Uso:
    cd apps/api && alembic upgrade head            # aplicar migraciones pendientes
    cd apps/api && alembic revision --autogenerate -m "msg"  # generar migración
    cd apps/api && alembic stamp head              # marcar DB como up-to-date
    cd apps/api && alembic history                 # ver historial
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import create_engine, pool

from alembic import context

# --- Asegurar que el paquete `app` está en sys.path ---
_API_DIR = Path(__file__).resolve().parents[1]
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

# Importar todos los modelos para que SQLModel.metadata los tenga registrados
from sqlmodel import SQLModel  # noqa: E402

from app import models  # noqa: F401, E402  (side-effect: registra modelos)
from app.core.config import settings  # noqa: E402

# Alembic Config object (lee alembic.ini)
config = context.config

# NOTA: NO usar config.set_main_option("sqlalchemy.url", ...) porque configparser
# interpreta `%` como sintaxis de interpolación y nuestras URLs llevan `%2A` y
# similares URL-encoded. En su lugar pasamos la URL directamente a create_engine.
DB_URL = settings.database_url

# Logging desde alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# `target_metadata` lo usa autogenerate para comparar el modelo Python con la DB
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Modo offline: emite SQL sin conectar a la DB."""
    context.configure(
        url=DB_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=False,  # ruido entre SQLModel/Postgres types — cambios reales a mano
        compare_server_default=False,
        include_object=_include_object,
        render_item=_render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Modo online: aplica migraciones contra la DB."""
    connectable = create_engine(DB_URL, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=False,
            compare_server_default=False,
            include_schemas=False,
            include_object=_include_object,
            render_item=_render_item,
        )
        with context.begin_transaction():
            context.run_migrations()


# Constraints/índices declarados FUERA de SQLModel (via SQL puro en migraciones)
# que Alembic no debe intentar borrar/recrear.
_IGNORED_CONSTRAINTS = {
    "tenants_supabase_user_id_fkey",  # FK a auth.users — Supabase Auth maneja el schema
}
_IGNORED_INDEXES = {
    "ix_tenants_supabase_user_id",  # índice condicional WHERE supabase_user_id IS NOT NULL
}


def _include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    """Excluye objetos no gestionados por nuestro modelo SQLModel."""
    # Ignora cualquier tabla del schema `auth` de Supabase
    if type_ == "table" and getattr(obj, "schema", None) == "auth":
        return False
    if type_ == "foreign_key_constraint" and name in _IGNORED_CONSTRAINTS:
        return False
    if type_ == "index" and name in _IGNORED_INDEXES:
        return False
    return True


def _render_item(type_, obj, autogen_context):  # type: ignore[no-untyped-def]
    """Renderer custom — silencia los `modify_comment` (cosméticos)."""
    if type_ == "comment":
        return False  # no genera código para comments
    return False  # default rendering para todo lo demás


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
