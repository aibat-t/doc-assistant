"""Проверки живости и готовности.

/health — процесс жив (для liveness-проб).
/health/ready — доступны ли Postgres, RabbitMQ и Redis (для readiness-проб и отладки).
"""

import asyncio

import aio_pika
import asyncpg
import redis.asyncio as aioredis
from fastapi import APIRouter, Response, status

from docs_assistant.config import get_settings

router = APIRouter(tags=["health"])

CHECK_TIMEOUT_S = 2.0


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _check_postgres(url: str) -> None:
    # asyncpg не понимает префикс драйвера SQLAlchemy
    conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        await conn.execute("SELECT 1")
        has_vector = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
        )
        if not has_vector:
            raise RuntimeError("расширение pgvector не установлено")
    finally:
        await conn.close()


async def _check_rabbitmq(url: str) -> None:
    conn = await aio_pika.connect(url)
    await conn.close()


async def _check_redis(url: str) -> None:
    client = aioredis.from_url(url)
    try:
        await client.ping()
    finally:
        await client.aclose()


async def _run(check, url: str) -> str:
    try:
        await asyncio.wait_for(check(url), timeout=CHECK_TIMEOUT_S)
        return "ok"
    except Exception as exc:
        return f"error: {type(exc).__name__}: {exc}"


@router.get("/health/ready")
async def ready(response: Response) -> dict[str, object]:
    s = get_settings()
    results = await asyncio.gather(
        _run(_check_postgres, s.database_url),
        _run(_check_rabbitmq, s.rabbitmq_url),
        _run(_check_redis, s.redis_url),
    )
    checks = dict(zip(["postgres", "rabbitmq", "redis"], results, strict=True))
    all_ok = all(v == "ok" for v in checks.values())
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if all_ok else "degraded", "checks": checks}
