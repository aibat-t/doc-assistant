"""Логика решения регистратора без БД. Сценарии с настоящим Postgres — в integration/."""

from docs_assistant.ingestion.registry import RegisterAction, decide
from docs_assistant.ingestion.text import content_hash, normalize_text


def h(text: str) -> str:
    return content_hash(normalize_text(text))


def test_new_document_is_created():
    assert decide(None, h("Статья 1.")) is RegisterAction.created


def test_same_text_is_unchanged():
    assert decide(h("Статья 1."), h("Статья 1.")) is RegisterAction.unchanged


def test_trailing_whitespace_only_is_unchanged():
    assert (
        decide(h("Статья 1.\nТекст."), h("Статья 1.  \r\nТекст.\t\n")) is RegisterAction.unchanged
    )


def test_changed_text_is_updated():
    assert decide(h("Статья 1.\nТекст."), h("Статья 1.\nНовый текст.")) is RegisterAction.updated
