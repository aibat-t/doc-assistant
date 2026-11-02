"""Временная чистая БД для интеграционных тестов.

На каждую сессию pytest создаётся отдельная база `rag_test_<случайный суффикс>`, к ней
применяются миграции Alembic, после тестов база удаляется. Рабочие данные в `rag` не трогаются,
и заодно проверяется, что миграции поднимают схему с нуля.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from docs_assistant.config import get_settings


def _asyncpg_dsn(url: str) -> str:
    # asyncpg не понимает префикс драйвера SQLAlchemy
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _admin(url: str, sql: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(url))
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def migrated_db_url() -> Iterator[str]:
    base_url = get_settings().database_url
    name = f"rag_test_{uuid.uuid4().hex[:8]}"
    test_url = make_url(base_url).set(database=name).render_as_string(hide_password=False)

    asyncio.run(_admin(base_url, f'CREATE DATABASE "{name}"'))
    try:
        # pgvector в новой базе нужно включить отдельно (init.sql выполняется только для `rag`)
        asyncio.run(_admin(test_url, "CREATE EXTENSION IF NOT EXISTS vector"))
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", test_url)
        command.upgrade(cfg, "head")
        yield test_url
    finally:
        asyncio.run(_admin(base_url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture
async def session(migrated_db_url: str) -> AsyncIterator[AsyncSession]:
    """Сессия в транзакции, которая откатывается после теста: тесты не видят данных друг друга."""
    engine = create_async_engine(migrated_db_url, poolclass=NullPool)
    async with engine.connect() as conn:
        trans = await conn.begin()
        async with AsyncSession(bind=conn, expire_on_commit=False) as s:
            yield s
        await trans.rollback()
    await engine.dispose()
