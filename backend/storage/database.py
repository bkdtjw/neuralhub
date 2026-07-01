from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.common.errors import AgentError
from backend.config.settings import settings
from backend.storage.models import Base

SessionFactory = async_sessionmaker[AsyncSession]
_PROVIDER_ROLES_MIGRATION_SQL = (
    "ALTER TABLE providers "
    "ADD COLUMN IF NOT EXISTS roles VARCHAR(200) NOT NULL DEFAULT ''"
)
_MESSAGE_KIND_MIGRATION_SQL = (
    "ALTER TABLE messages "
    "ADD COLUMN IF NOT EXISTS kind VARCHAR(30) NOT NULL DEFAULT 'user_request'"
)
_MESSAGE_EPHEMERAL_MIGRATION_SQL = (
    "ALTER TABLE messages "
    "ADD COLUMN IF NOT EXISTS ephemeral BOOLEAN NOT NULL DEFAULT false"
)
_PGVECTOR_EXTENSION_SQL = "CREATE EXTENSION IF NOT EXISTS vector"


def build_session_factory(database_url: str) -> tuple[AsyncEngine, SessionFactory]:
    try:
        backend_name = make_url(database_url).get_backend_name()
    except Exception as exc:  # noqa: BLE001
        raise AgentError(
            "DB_UNSUPPORTED_BACKEND",
            f"Unsupported database URL: {database_url}",
        ) from exc
    if not backend_name.startswith("postgresql"):
        raise AgentError("DB_UNSUPPORTED_BACKEND", f"Unsupported database backend: {backend_name}")
    engine = create_async_engine(database_url, **_build_postgres_engine_kwargs())
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _build_postgres_engine_kwargs() -> dict[str, object]:
    return {
        "pool_size": settings.database_pool_size,
        "max_overflow": settings.database_max_overflow,
        "pool_timeout": settings.database_pool_timeout,
        "pool_recycle": settings.database_pool_recycle,
        "pool_pre_ping": True,
    }


engine, session_factory = build_session_factory(settings.database_url)


async def init_db(target_engine: AsyncEngine | None = None) -> None:
    resolved_engine = target_engine or engine
    try:
        async with resolved_engine.begin() as connection:
            await connection.execute(text(_PGVECTOR_EXTENSION_SQL))
            await connection.run_sync(Base.metadata.create_all)
            await connection.execute(text(_PROVIDER_ROLES_MIGRATION_SQL))
            await connection.execute(text(_MESSAGE_KIND_MIGRATION_SQL))
            await connection.execute(text(_MESSAGE_EPHEMERAL_MIGRATION_SQL))
    except Exception as exc:  # noqa: BLE001
        raise AgentError("DB_INIT_ERROR", str(exc)) from exc


@asynccontextmanager
async def get_db_session(factory: SessionFactory | None = None) -> AsyncIterator[AsyncSession]:
    try:
        async with (factory or session_factory)() as session:
            yield session
    except Exception as exc:  # noqa: BLE001
        raise AgentError("DB_SESSION_ERROR", str(exc)) from exc


__all__ = [
    "SessionFactory",
    "build_session_factory",
    "engine",
    "get_db_session",
    "init_db",
    "session_factory",
]
