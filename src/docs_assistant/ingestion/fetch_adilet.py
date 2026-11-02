"""Скачивание HTML документов с adilet в `data/raw/<external_id>_<lang>.html`.

Вежливый краулер: один запрос за раз, пауза между запросами, User-Agent с контактом,
ретраи только на временные ошибки (5xx, обрыв соединения, таймаут).
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import httpx

from docs_assistant import __version__
from docs_assistant.config import Settings
from docs_assistant.ingestion.sources import Source

log = logging.getLogger(__name__)

# Признаки страницы документа на old.adilet.zan.kz. Проверяем по сырым байтам, без парсинга:
# кодекс весит до 3 МБ, а здесь нужен только быстрый ответ «это текст закона или нет».
_MAIN_CONTENT_MARKER = b"<article"
_REPEALED_MARKER = b"status_yts"  # метка «Утративший силу»


class FetchStatus(StrEnum):
    downloaded = "downloaded"
    skipped = "skipped"  # файл уже есть, а --force не указан
    repealed = "repealed"  # документ утратил силу — в корпус действующего права не берём
    failed = "failed"


@dataclass(frozen=True)
class FetchResult:
    source: Source
    status: FetchStatus
    path: Path
    error: str | None = None


class _RetryableError(Exception):
    pass


def user_agent(contact: str) -> str:
    agent = f"docs-assistant/{__version__} (educational RAG project"
    return f"{agent}; contact: {contact})" if contact else f"{agent})"


class _Throttle:
    """Гарантирует паузу не меньше `delay_s` между началами запросов."""

    def __init__(self, delay_s: float) -> None:
        self._delay_s = delay_s
        self._last: float | None = None

    async def wait(self) -> None:
        if self._last is not None:
            remaining = self._delay_s - (time.monotonic() - self._last)
            if remaining > 0:
                await asyncio.sleep(remaining)
        self._last = time.monotonic()


async def _download(client: httpx.AsyncClient, url: str, throttle: _Throttle) -> bytes:
    await throttle.wait()
    try:
        resp = await client.get(url)
    except httpx.TransportError as exc:  # таймаут, обрыв, DNS — стоит повторить
        raise _RetryableError(f"{type(exc).__name__}: {exc}") from exc
    if resp.status_code >= 500:
        raise _RetryableError(f"HTTP {resp.status_code}")
    resp.raise_for_status()  # 4xx повторять бессмысленно
    return resp.content


async def fetch_one(
    client: httpx.AsyncClient,
    source: Source,
    settings: Settings,
    throttle: _Throttle,
    *,
    force: bool = False,
) -> FetchResult:
    path = settings.raw_dir / source.raw_filename()
    if path.exists() and not force:
        return FetchResult(source, FetchStatus.skipped, path)

    url = source.fetch_url(settings.fetch_base_url)
    attempts = max(1, settings.fetch_retries)
    content: bytes | None = None
    for attempt in range(1, attempts + 1):
        try:
            content = await _download(client, url, throttle)
            break
        except _RetryableError as exc:
            if attempt == attempts:
                return FetchResult(
                    source, FetchStatus.failed, path, f"{exc} после {attempt} попыток"
                )
            backoff = 2**attempt  # экспоненциальная пауза: 2, 4, 8 с
            log.warning("%s: %s, повтор через %s с", url, exc, backoff)
            await asyncio.sleep(backoff)
        except httpx.HTTPStatusError as exc:
            return FetchResult(source, FetchStatus.failed, path, f"HTTP {exc.response.status_code}")
    assert content is not None

    if _MAIN_CONTENT_MARKER not in content:
        return FetchResult(source, FetchStatus.failed, path, "на странице нет текста документа")
    if _REPEALED_MARKER in content:
        return FetchResult(source, FetchStatus.repealed, path, "документ утратил силу")

    # Пишем во временный файл и переименовываем: если процесс прервётся посреди записи,
    # в data/raw не останется обрезанного файла, который следующий запуск посчитал бы скачанным.
    # Сохраняем байты как есть — это «сырой» слой, кодировку разберёт парсер.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(content)
    tmp.replace(path)
    return FetchResult(source, FetchStatus.downloaded, path)


async def fetch_all(
    sources: list[Source],
    settings: Settings,
    *,
    force: bool = False,
    client: httpx.AsyncClient | None = None,
) -> list[FetchResult]:
    """Скачать документы по очереди. Ошибка одного документа не останавливает остальные."""
    own_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            headers={"User-Agent": user_agent(settings.fetch_contact)},
            timeout=settings.fetch_timeout_s,
            follow_redirects=True,
        )
    throttle = _Throttle(settings.fetch_delay_s)
    results: list[FetchResult] = []
    try:
        for i, source in enumerate(sources, 1):
            result = await fetch_one(client, source, settings, throttle, force=force)
            suffix = f": {result.error}" if result.error else ""
            log.info("[%d/%d] %s %s%s", i, len(sources), result.status, source.url, suffix)
            results.append(result)
    finally:
        if own_client:
            await client.aclose()
    return results
