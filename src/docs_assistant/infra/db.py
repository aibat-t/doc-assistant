"""Async-движок SQLAlchemy и фабрика сессий.

Движок держит пул соединений, поэтому создаётся один раз на процесс.
Сессия — короткоживущая единица работы (аналог EntityManager в JPA).
"""

from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from docs_assistant.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: после commit объекты остаются читаемыми без нового запроса в БД.
    # В async это важно — ленивая подгрузка атрибута вне await упадёт.
    return async_sessionmaker(get_engine(), expire_on_commit=False)
