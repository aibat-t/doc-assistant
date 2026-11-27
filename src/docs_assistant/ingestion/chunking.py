"""Нарезка разобранного документа на чанки для поиска.

Единица — статья: в праве это смысловая единица, на неё же ссылаются в ответе
(«ст. 87 Трудового кодекса»). Короткая статья — один чанк. Длинная режется по пунктам,
слишком длинный пункт — по строкам (подпунктам), затем по предложениям, в крайнем случае
по словам. Соседние куски одной статьи перекрываются на ~12 %, чтобы мысль на границе
не терялась.

В начало каждого чанка пишем «хлебные крошки»:
`Трудовой кодекс Республики Казахстан > Глава 10. … > Статья 87. …`. Без них кусок
«3. Работник вправе…» не знает, из какого закона он, а запрос «статья 87» не находится
полнотекстовым поиском.

Длина меряется токенизатором самой модели эмбеддингов (multilingual-e5-large): у неё окно
512 токенов, всё длиннее молча обрезается при кодировании. Лимит чанка ниже окна, потому что
к тексту ещё добавятся префикс `passage: ` и служебные токены.
"""

import re
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from docs_assistant.ingestion.parsers.html_adilet import Block, Level

TokenCounter = Callable[[str], int]

CRUMB_SEPARATOR = " > "

# Пункт статьи: «1. Текст», «2-1. Текст». Подпункты «1) …» остаются внутри своего пункта.
_POINT_START = re.compile(r"^\d+(?:-\d+)*\.\s")
# Конец предложения: точка, ;, :, !, ? и пробел перед заглавной буквой, цифрой или кавычкой
_SENTENCE_END = re.compile(r"(?<=[.;:!?])\s+(?=[А-ЯЁӘҒҚҢӨҰҮҺІA-Z0-9«\"(])")


@dataclass(frozen=True)
class DocumentInfo:
    """Что чанкеру нужно знать о документе (берётся из таблицы documents)."""

    id: uuid.UUID
    version: int
    title: str
    lang: str
    doc_type: str


@dataclass(frozen=True)
class Chunk:
    text: str  # крошки + текст, ровно это уходит в эмбеддинг и в tsvector
    document_id: uuid.UUID
    document_version: int
    chunk_index: int
    section_path: list[str]  # заголовки от раздела до статьи, без названия документа
    article_number: str | None
    lang: str

    def metadata(self) -> dict[str, Any]:
        """Поля для колонки chunks.metadata (jsonb) на этапе 3."""
        return {
            "section_path": self.section_path,
            "article_number": self.article_number,
            "lang": self.lang,
        }


def document_label(title: str, doc_type: str, lang: str) -> str:
    """Название документа для крошек.

    Кодексы уже называются полностью («Трудовой кодекс Республики Казахстан»), а законы
    в базе записаны как «О связи» — без слова «Закон» крошка непонятна.
    """
    if doc_type == "law" and lang == "ru" and re.match(r"^Об?\s", title):
        return f"Закон Республики Казахстан «{title}»"
    return title


# --- Подсчёт токенов ---------------------------------------------------------------------


@lru_cache(maxsize=2)
def e5_token_counter(model_name: str = "intfloat/multilingual-e5-large") -> TokenCounter:
    """Счётчик токенов токенизатором модели эмбеддингов.

    Пакет `tokenizers` лёгкий (без torch), а файл токенизатора (~17 МБ) скачивается с
    Hugging Face один раз и кэшируется. В юнит-тестах вместо него — простой счётчик слов.
    """
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_pretrained(model_name)

    def count(text: str) -> int:
        return len(tokenizer.encode(text, add_special_tokens=False).ids)

    return count


# --- Нарезка -----------------------------------------------------------------------------


def _split_points(lines: list[str]) -> list[str]:
    """Сгруппировать строки статьи по пунктам: пункт + его подпункты и абзацы."""
    points: list[list[str]] = []
    for line in lines:
        if not points or _POINT_START.match(line):
            points.append([line])
        else:
            points[-1].append(line)
    return ["\n".join(p) for p in points]


def _split_words(text: str, budget: int, count: TokenCounter) -> list[str]:
    """Последний рубеж: предложение длиннее лимита (таблица, перечень через запятую)."""
    pieces: list[str] = []
    current: list[str] = []
    for word in text.split(" "):
        if current and count(" ".join([*current, word])) > budget:
            pieces.append(" ".join(current))
            current = []
        current.append(word)
    if current:
        pieces.append(" ".join(current))
    return pieces


def _units(text: str, budget: int, count: TokenCounter) -> list[str]:
    """Разбить текст на куски не длиннее budget: пункты → строки → предложения → слова."""
    if count(text) <= budget:
        return [text]
    lines = text.split("\n")
    if len(lines) > 1:
        points = _split_points(lines)
        # Один пункт на всю статью — дальше режем по строкам
        parts = points if len(points) > 1 else lines
        return [u for part in parts for u in _units(part, budget, count)]
    sentences = _SENTENCE_END.split(text)
    if len(sentences) > 1:
        return [u for s in sentences for u in _units(s, budget, count)]
    return _split_words(text, budget, count)


def _tail(text: str, overlap: int, count: TokenCounter) -> str:
    """Хвост предыдущего куска для перекрытия: целые строки или предложения с конца,
    не больше overlap токенов. Обрывков фраз в перекрытии не бывает."""
    taken: list[str] = []  # строки хвоста в обратном порядке
    for line in reversed(text.split("\n")):
        if count("\n".join([line, *reversed(taken)])) <= overlap:
            taken.append(line)
            continue
        # Строка целиком не влезла — берём её последние предложения и останавливаемся
        sentences: list[str] = []
        for sentence in reversed(_SENTENCE_END.split(line)):
            candidate = " ".join([sentence, *sentences])
            if count("\n".join([candidate, *reversed(taken)])) > overlap:
                break
            sentences.insert(0, sentence)
        if sentences:
            taken.append(" ".join(sentences))
        break
    return "\n".join(reversed(taken))


def split_text(text: str, budget: int, overlap: int, count: TokenCounter) -> list[str]:
    """Нарезать тело статьи на куски ≤ budget токенов с перекрытием ≤ overlap."""
    units = _units(text, budget, count)
    pieces: list[str] = []
    current: list[str] = []
    for unit in units:
        if current and count("\n".join([*current, unit])) > budget:
            pieces.append("\n".join(current))
            tail = _tail(pieces[-1], overlap, count) if overlap else ""
            # Перекрытие не должно выталкивать кусок за лимит
            current = [tail] if tail and count(f"{tail}\n{unit}") <= budget else []
        current.append(unit)
    if current:
        pieces.append("\n".join(current))
    return pieces


def chunk_document(
    blocks: Iterable[Block],
    doc: DocumentInfo,
    *,
    max_tokens: int,
    overlap_tokens: int,
    count: TokenCounter,
) -> list[Chunk]:
    """Превратить блоки парсера в чанки с крошками и метаданными.

    max_tokens — лимит на весь текст чанка вместе с крошками.
    """
    label = document_label(doc.title, doc.doc_type, doc.lang)
    # Стек открытых заголовков: «Раздел 2» закрывает все главы и параграфы прошлого раздела
    stack: list[Block] = []
    chunks: list[Chunk] = []

    for block in blocks:
        if block.level < Level.article:
            stack = [b for b in stack if b.level < block.level]
            stack.append(block)
            continue
        if not block.text:
            # Статья утратила силу: от неё остался заголовок и сноска «исключена Законом…»
            continue

        # Часть («Общая часть») в крошки не берём: она есть почти у всех статей и не помогает
        path = [b.heading for b in stack if b.level is not Level.part]
        if block.heading:
            path.append(block.heading)
        header = CRUMB_SEPARATOR.join([label, *path])
        budget = max_tokens - count(header + "\n")
        if budget < max_tokens // 4:
            # Очень длинные заголовки глав съедают почти весь лимит — оставляем только статью
            header = CRUMB_SEPARATOR.join([label, block.heading]) if block.heading else label
            budget = max_tokens - count(header + "\n")

        for piece in split_text(block.text, budget, overlap_tokens, count):
            chunks.append(
                Chunk(
                    text=f"{header}\n{piece}",
                    document_id=doc.id,
                    document_version=doc.version,
                    chunk_index=len(chunks),
                    section_path=path,
                    article_number=block.number if block.level is Level.article else None,
                    lang=doc.lang,
                )
            )
    return chunks
