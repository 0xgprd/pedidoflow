-- Pedidoflow - Inicialización Postgres
-- Activa pgvector. Las tablas se crean por SQLModel/Alembic en el backend.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
