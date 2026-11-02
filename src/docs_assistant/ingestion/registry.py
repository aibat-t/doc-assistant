"""Регистратор документов: решает, новый документ, неизменный или новая версия.

Версия меняется только тогда, когда изменился **нормализованный** текст закона.
Хеш от сырого HTML не годится: баннер, счётчик или новая вёрстка сайта давали бы
«новую версию» и лишнюю переиндексацию без изменений в самом законе.
"""

import asyncio
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from docs_assistant.ingestion.sources import Source
from docs_assistant.ingestion.text import (
    content_hash,
    extract_main_text,
    extract_title,
    normalize_text,
)
from docs_assistant.models import Document, DocumentStatus


class RegisterAction(StrEnum):
    created = "created"  # документа не было → version=1
    unchanged = "unchanged"  # хеш совпал → ничего не делаем
    updated = "updated"  # хеш другой → version+1, снова в очередь на индексацию


def decide(existing_hash: str | None, new_hash: str) -> RegisterAction:
    if existing_hash is None:
        return RegisterAction.created
    if existing_hash == new_hash:
        return RegisterAction.unchanged
    return RegisterAction.updated


@dataclass(frozen=True)
class RegisterResult:
    action: RegisterAction
    document_id: uuid.UUID
    version: int


async def register_document(
    session: AsyncSession,
    *,
    source_url: str,
    external_id: str,
    title: str,
    lang: str,
    doc_type: str,
    raw_path: str,
    text: str,
) -> RegisterResult:
    """Зарегистрировать документ по его тексту. Транзакцией управляет вызывающий код (commit).

    `text` — извлечённый текст документа; нормализация делается здесь, чтобы хеш
    всегда считался одинаково, откуда бы текст ни пришёл (adilet, загрузка через API).
    """
    new_hash = content_hash(normalize_text(text))

    # FOR UPDATE блокирует строку до конца транзакции: два параллельных register одного
    # документа (этап 4, API + reindex) не насчитают одну и ту же новую версию дважды.
    # Одновременное *создание* одного URL остановит unique-ограничение на source_url.
    doc = await session.scalar(
        select(Document).where(Document.source_url == source_url).with_for_update()
    )
    action = decide(doc.content_hash if doc else None, new_hash)

    if action is RegisterAction.created:
        doc = Document(
            source_url=source_url,
            external_id=external_id,
            title=title,
            lang=lang,
            doc_type=doc_type,
            content_hash=new_hash,
            version=1,
            status=DocumentStatus.queued,
            raw_path=raw_path,
        )
        session.add(doc)
    elif action is RegisterAction.updated:
        assert doc is not None
        doc.content_hash = new_hash
        doc.version += 1
        doc.status = DocumentStatus.queued
        doc.error = None
        doc.title = title
        doc.raw_path = raw_path

    assert doc is not None
    await session.flush()  # чтобы id нового документа был известен до commit
    return RegisterResult(action, doc.id, doc.version)


async def register_file(session: AsyncSession, source: Source, path: Path) -> RegisterResult:
    """Зарегистрировать скачанную страницу adilet."""
    # Чтение и разбор HTML (до 3 МБ) — блокирующие операции: уносим их в поток,
    # чтобы не останавливать event loop (на этапе 4 этот код будет работать внутри API)
    html = await asyncio.to_thread(path.read_bytes)
    text = await asyncio.to_thread(extract_main_text, html)
    assert source.doc_type is not None  # заполняется валидатором Source
    return await register_document(
        session,
        source_url=source.url,
        external_id=source.external_id,
        title=source.title or extract_title(html) or source.external_id,
        lang=source.lang,
        doc_type=source.doc_type,
        raw_path=path.as_posix(),
        text=text,
    )
