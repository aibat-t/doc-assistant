"""Миграции и модели согласованы. Нужен `docker compose up -d --wait`."""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from docs_assistant.models import Base

pytestmark = pytest.mark.integration


async def test_models_match_migrations(migrated_db_url: str):
    # То же сравнение, что делает `alembic revision --autogenerate`: если оно что-то нашло,
    # значит модель поменяли, а миграцию написать забыли (или наоборот)
    engine = create_async_engine(migrated_db_url, poolclass=NullPool)
    async with engine.connect() as conn:
        diff = await conn.run_sync(
            lambda sync_conn: compare_metadata(MigrationContext.configure(sync_conn), Base.metadata)
        )
    await engine.dispose()
    assert diff == []
