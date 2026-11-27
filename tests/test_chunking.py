import itertools
import uuid

import pytest

from docs_assistant.ingestion.chunking import (
    CRUMB_SEPARATOR,
    DocumentInfo,
    chunk_document,
    document_label,
    split_text,
)
from docs_assistant.ingestion.parsers.html_adilet import Block, Level


def words(text: str) -> int:
    """Счётчик «токенов» для тестов: слова. Настоящий токенизатор e5 не нужен — проверяем логику."""
    return len(text.split())


DOC = DocumentInfo(
    id=uuid.UUID(int=1),
    version=3,
    title="Трудовой кодекс Республики Казахстан",
    lang="ru",
    doc_type="code",
)


def _point(n: int, size: int) -> str:
    return f"{n}. " + " ".join(f"Слово{n}_{i}." for i in range(size - 1))


def test_short_article_is_one_chunk_with_breadcrumbs():
    blocks = [
        Block(Level.part, "ОБЩАЯ ЧАСТЬ"),
        Block(Level.section, "РАЗДЕЛ 1. ОБЩИЕ ПОЛОЖЕНИЯ", number="1"),
        Block(Level.chapter, "Глава 5. Трудовой договор", number="5"),
        Block(Level.article, "Статья 87. Расторжение", "1. Текст пункта.", number="87"),
    ]
    [chunk] = chunk_document(blocks, DOC, max_tokens=100, overlap_tokens=10, count=words)
    header, body = chunk.text.split("\n", 1)
    # Часть («Общая часть») в крошки не попадает, остальное — по порядку
    assert header == CRUMB_SEPARATOR.join(
        [
            "Трудовой кодекс Республики Казахстан",
            "РАЗДЕЛ 1. ОБЩИЕ ПОЛОЖЕНИЯ",
            "Глава 5. Трудовой договор",
            "Статья 87. Расторжение",
        ]
    )
    assert body == "1. Текст пункта."
    assert chunk.article_number == "87"
    assert chunk.section_path == [
        "РАЗДЕЛ 1. ОБЩИЕ ПОЛОЖЕНИЯ",
        "Глава 5. Трудовой договор",
        "Статья 87. Расторжение",
    ]
    assert (chunk.document_id, chunk.document_version, chunk.chunk_index) == (DOC.id, 3, 0)
    assert chunk.metadata() == {
        "section_path": chunk.section_path,
        "article_number": "87",
        "lang": "ru",
    }


def test_new_heading_closes_deeper_levels():
    blocks = [
        Block(Level.section, "Раздел 1"),
        Block(Level.chapter, "Глава 1"),
        Block(Level.paragraph, "Параграф 1"),
        Block(Level.article, "Статья 1. А", "текст", number="1"),
        Block(Level.chapter, "Глава 2"),
        Block(Level.article, "Статья 2. Б", "текст", number="2"),
        Block(Level.section, "Раздел 2"),
        Block(Level.article, "Статья 3. В", "текст", number="3"),
    ]
    paths = [
        c.section_path
        for c in chunk_document(blocks, DOC, max_tokens=100, overlap_tokens=0, count=words)
    ]
    assert paths == [
        ["Раздел 1", "Глава 1", "Параграф 1", "Статья 1. А"],
        ["Раздел 1", "Глава 2", "Статья 2. Б"],
        ["Раздел 2", "Статья 3. В"],
    ]


def test_long_article_split_by_points_within_limit():
    body = "\n".join(_point(n, 30) for n in range(1, 11))  # 10 пунктов по 30 слов
    blocks = [Block(Level.article, "Статья 7. Длинная", body, number="7")]
    chunks = chunk_document(blocks, DOC, max_tokens=100, overlap_tokens=10, count=words)

    assert len(chunks) > 1
    assert all(words(c.text) <= 100 for c in chunks)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert {c.article_number for c in chunks} == {"7"}
    # У каждого куска свои крошки
    assert all(
        c.text.startswith("Трудовой кодекс Республики Казахстан > Статья 7.") for c in chunks
    )
    # Ни один пункт не потерян
    joined = "\n".join(c.text for c in chunks)
    for n in range(1, 11):
        assert f"\n{n}. Слово{n}_0." in joined


def test_neighbour_chunks_overlap():
    body = "\n".join(_point(n, 30) for n in range(1, 7))
    pieces = split_text(body, budget=80, overlap=10, count=words)
    assert len(pieces) > 1
    for prev, nxt in itertools.pairwise(pieces):
        first_line = nxt.split("\n")[0]
        # Первая строка следующего куска — хвост предыдущего (целые предложения)
        assert prev.endswith(first_line)
        assert words(first_line) <= 10


def test_huge_sentence_falls_back_to_words():
    body = " ".join(f"w{i}" for i in range(250))  # одно «предложение» без точек
    pieces = split_text(body, budget=50, overlap=0, count=words)
    assert all(words(p) <= 50 for p in pieces)
    assert " ".join(pieces).split() == body.split()


def test_long_point_split_by_sentences():
    point = "1. " + " ".join(f"Предложение номер {i} из пяти слов." for i in range(40))
    pieces = split_text(point, budget=60, overlap=0, count=words)
    assert len(pieces) > 1
    # Режем на границе предложений: каждый кусок заканчивается точкой
    assert all(p.endswith(".") for p in pieces)


def test_excluded_article_is_skipped_and_preamble_kept():
    blocks = [
        Block(Level.preamble, "Преамбула", "Настоящий Закон регулирует отношения."),
        Block(Level.article, "Статья 1. Исключена", "", number="1"),
        Block(Level.article, "Статья 2. Действует", "Текст.", number="2"),
    ]
    chunks = chunk_document(blocks, DOC, max_tokens=100, overlap_tokens=0, count=words)
    assert [c.article_number for c in chunks] == [None, "2"]
    assert chunks[0].section_path == ["Преамбула"]


@pytest.mark.parametrize(
    ("title", "doc_type", "lang", "expected"),
    [
        ("О связи", "law", "ru", "Закон Республики Казахстан «О связи»"),
        ("Об образовании", "law", "ru", "Закон Республики Казахстан «Об образовании»"),
        (
            "Трудовой кодекс Республики Казахстан",
            "code",
            "ru",
            "Трудовой кодекс Республики Казахстан",
        ),
        (
            "Қазақстан Республикасының Еңбек кодексі",
            "code",
            "kk",
            "Қазақстан Республикасының Еңбек кодексі",
        ),
    ],
)
def test_document_label(title, doc_type, lang, expected):
    assert document_label(title, doc_type, lang) == expected
