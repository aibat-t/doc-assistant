"""Извлечение основного текста страницы adilet и его нормализация для хеширования.

Это минимальный экстрактор для этапа 1: он нужен, чтобы хеш зависел только от текста закона.
Полноценный разбор структуры (разделы, главы, статьи) — на этапе 2, в `ingestion/parsers/`.
"""

import hashlib
import re
from html import unescape

from bs4 import BeautifulSoup

_TITLE = re.compile(rb"<title>(.*?)</title>", re.DOTALL | re.IGNORECASE)

# На странице документа old.adilet.zan.kz текст закона лежит внутри <article>.
# Всё остальное (меню, баннер «переходите на новый портал», вкладки) — шум, который
# меняется независимо от закона и не должен влиять на хеш.
MAIN_CONTENT_SELECTOR = "article"

_BLANK_LINES = re.compile(r"\n{2,}")


class MainContentNotFoundError(ValueError):
    """На странице нет блока с текстом документа (изменилась вёрстка или это не страница закона)."""


def extract_main_text(html: str | bytes) -> str:
    """Вернуть текст основного блока страницы, без тегов и служебных элементов."""
    soup = BeautifulSoup(html, "lxml")
    main = soup.select_one(MAIN_CONTENT_SELECTOR)
    if main is None:
        raise MainContentNotFoundError(f"не найден элемент {MAIN_CONTENT_SELECTOR!r}")
    for tag in main(["script", "style", "noscript"]):
        tag.decompose()
    # separator="\n": блочные элементы (<p>, <br>) превращаются в отдельные строки
    return main.get_text(separator="\n")


def extract_title(html: str | bytes) -> str | None:
    """Название документа из <title> без суффикса сайта (« - ИПС "Әділет"»)."""
    # Регулярка вместо второго разбора всего HTML: кодекс весит мегабайты, а <title> в начале
    raw = html if isinstance(html, bytes) else html.encode("utf-8")
    m = _TITLE.search(raw)
    if m is None:
        return None
    title = unescape(m.group(1).decode("utf-8", errors="replace")).rsplit(" - ", 1)[0]
    return " ".join(title.split()) or None


def normalize_text(text: str) -> str:
    """Привести текст к каноническому виду, чтобы косметика не меняла хеш.

    - единые переводы строк (\\r\\n и \\r → \\n);
    - неразрывные пробелы → обычные;
    - пробелы по краям каждой строки убраны (отступы в HTML — это вёрстка, а не текст);
    - пустые строки удалены.
    Пробелы внутри строки не трогаем: там они часть текста.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    lines = (line.strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def content_hash(normalized_text: str) -> str:
    """SHA-256 нормализованного текста, 64 hex-символа (колонка documents.content_hash)."""
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
