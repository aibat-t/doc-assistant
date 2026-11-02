"""Регистратор на настоящем Postgres. Нужен `docker compose up -d --wait`."""

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from docs_assistant.ingestion.registry import RegisterAction, register_document
from docs_assistant.models import Document, DocumentStatus

pytestmark = pytest.mark.integration

URL = "https://adilet.zan.kz/rus/docs/K1500000414"
TEXT = "Статья 1. Основные понятия\n1. В настоящем Кодексе используются понятия."


async def register(session: AsyncSession, text_: str) -> RegisterAction:
    result = await register_document(
        session,
        source_url=URL,
        external_id="K1500000414",
        title="Трудовой кодекс Республики Казахстан",
        lang="ru",
        doc_type="code",
        raw_path="data/raw/K1500000414_ru.html",
        text=text_,
    )
    return result.action


async def get_doc(session: AsyncSession) -> Document:
    doc = await session.scalar(select(Document).where(Document.source_url == URL))
    assert doc is not None
    await session.refresh(doc)
    return doc


async def test_migration_created_documents_table(session: AsyncSession):
    columns = (
        await session.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'documents'"
            )
        )
    ).scalars()
    assert {"id", "source_url", "content_hash", "version", "status"} <= set(columns)


async def test_first_register_creates_version_1(session: AsyncSession):
    assert await register(session, TEXT) is RegisterAction.created
    doc = await get_doc(session)
    assert (doc.version, doc.status) == (1, DocumentStatus.queued)
    assert len(doc.content_hash) == 64
    assert doc.created_at is not None


async def test_repeated_register_does_not_duplicate(session: AsyncSession):
    await register(session, TEXT)
    assert await register(session, TEXT) is RegisterAction.unchanged
    count = await session.scalar(
        select(func.count()).select_from(Document).where(Document.source_url == URL)
    )
    assert count == 1
    assert (await get_doc(session)).version == 1


async def test_changed_text_bumps_version_and_requeues(session: AsyncSession):
    await register(session, TEXT)
    doc = await get_doc(session)
    doc.status, doc.error = DocumentStatus.failed, "старая ошибка"
    await session.flush()

    assert await register(session, TEXT + "\n2. Новый пункт.") is RegisterAction.updated
    doc = await get_doc(session)
    assert (doc.version, doc.status, doc.error) == (2, DocumentStatus.queued, None)


async def test_trailing_whitespace_does_not_change_version(session: AsyncSession):
    await register(session, TEXT)
    reformatted = TEXT.replace("\n", "   \r\n\r\n") + "  \n"
    assert await register(session, reformatted) is RegisterAction.unchanged
    assert (await get_doc(session)).version == 1
