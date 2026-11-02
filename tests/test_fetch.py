"""Загрузчик adilet: сеть подменяется httpx.MockTransport."""

from pathlib import Path

import httpx
import pytest

from docs_assistant.config import Settings
from docs_assistant.ingestion import fetch_adilet
from docs_assistant.ingestion.fetch_adilet import FetchStatus, fetch_all, user_agent
from docs_assistant.ingestion.sources import Source

SOURCE = Source(url="https://adilet.zan.kz/rus/docs/K1500000414", lang="ru")
PAGE = b"<html><article><p>\xd0\xa1\xd1\x82\xd0\xb0\xd1\x82\xd1\x8c\xd1\x8f 1.</p></article></html>"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, raw_dir=tmp_path, fetch_delay_s=0, fetch_retries=3)


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(fetch_adilet.asyncio, "sleep", fake_sleep)
    return sleeps


def client_with(responses: list[httpx.Response], seen: list[httpx.Request]) -> httpx.AsyncClient:
    it = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return next(it)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_downloads_from_fetch_base_url(settings):
    seen: list[httpx.Request] = []
    async with client_with([httpx.Response(200, content=PAGE)], seen) as client:
        [result] = await fetch_all([SOURCE], settings, client=client)
    assert result.status is FetchStatus.downloaded
    assert str(seen[0].url) == "https://old.adilet.zan.kz/rus/docs/K1500000414"
    assert (settings.raw_dir / "K1500000414_ru.html").read_bytes() == PAGE
    assert not list(settings.raw_dir.glob("*.part"))


async def test_existing_file_is_skipped_unless_force(settings):
    path = settings.raw_dir / "K1500000414_ru.html"
    path.write_bytes(b"old")
    seen: list[httpx.Request] = []
    async with client_with([httpx.Response(200, content=PAGE)], seen) as client:
        [skipped] = await fetch_all([SOURCE], settings, client=client)
        assert skipped.status is FetchStatus.skipped
        assert not seen
        [forced] = await fetch_all([SOURCE], settings, client=client, force=True)
    assert forced.status is FetchStatus.downloaded
    assert path.read_bytes() == PAGE


async def test_retries_on_5xx_with_backoff(settings, no_backoff):
    seen: list[httpx.Request] = []
    responses = [httpx.Response(502), httpx.Response(503), httpx.Response(200, content=PAGE)]
    async with client_with(responses, seen) as client:
        [result] = await fetch_all([SOURCE], settings, client=client)
    assert result.status is FetchStatus.downloaded
    assert len(seen) == 3
    assert no_backoff == [2, 4]


async def test_gives_up_after_max_retries(settings):
    seen: list[httpx.Request] = []
    async with client_with([httpx.Response(500)] * 3, seen) as client:
        [result] = await fetch_all([SOURCE], settings, client=client)
    assert result.status is FetchStatus.failed
    assert len(seen) == 3
    assert not result.path.exists()


async def test_no_retry_on_404(settings):
    seen: list[httpx.Request] = []
    async with client_with([httpx.Response(404)], seen) as client:
        [result] = await fetch_all([SOURCE], settings, client=client)
    assert result.status is FetchStatus.failed
    assert result.error == "HTTP 404"
    assert len(seen) == 1


async def test_repealed_document_is_not_saved(settings):
    page = b'<span class="status status_yts">...</span><article>text</article>'
    seen: list[httpx.Request] = []
    async with client_with([httpx.Response(200, content=page)], seen) as client:
        [result] = await fetch_all([SOURCE], settings, client=client)
    assert result.status is FetchStatus.repealed
    assert not result.path.exists()


async def test_page_without_text_fails(settings):
    # Так выглядит новый SPA-портал: текст закона подгружается скриптом
    page = b'<html><body><div id="root"></div></body></html>'
    seen: list[httpx.Request] = []
    async with client_with([httpx.Response(200, content=page)], seen) as client:
        [result] = await fetch_all([SOURCE], settings, client=client)
    assert result.status is FetchStatus.failed


async def test_throttle_pauses_between_requests(settings, no_backoff):
    settings.fetch_delay_s = 5
    other = Source(url="https://adilet.zan.kz/kaz/docs/K1500000414", lang="kk")
    seen: list[httpx.Request] = []
    responses = [httpx.Response(200, content=PAGE)] * 2
    async with client_with(responses, seen) as client:
        await fetch_all([SOURCE, other], settings, client=client)
    assert len(no_backoff) == 1
    assert 4 < no_backoff[0] <= 5


def test_user_agent_contains_contact():
    assert "contact: me@example.com" in user_agent("me@example.com")
    assert "contact" not in user_agent("")
