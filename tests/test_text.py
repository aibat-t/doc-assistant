import pytest

from docs_assistant.ingestion.text import (
    MainContentNotFoundError,
    content_hash,
    extract_main_text,
    extract_title,
    normalize_text,
)

PAGE = """<html><head>
<title>Трудовой кодекс Республики Казахстан - ИПС &quot;Әділет&quot;</title>
</head><body>
<div class="top-notice-banner">Информируем о переходе на новый НЦПС «Әділет»</div>
<article>
  <p><b>Статья 1. Основные понятия</b></p>
  <p>1. В настоящем Кодексе&nbsp;используются понятия.</p>
  <script>var x = 1;</script>
</article>
</body></html>"""


def test_extract_main_text_ignores_page_chrome():
    text = normalize_text(extract_main_text(PAGE))
    assert text == "Статья 1. Основные понятия\n1. В настоящем Кодексе используются понятия."
    assert "НЦПС" not in text  # баннер вне <article>
    assert "var x" not in text


def test_banner_change_does_not_change_hash():
    changed = PAGE.replace("Информируем о переходе", "Новый баннер")
    assert content_hash(normalize_text(extract_main_text(PAGE))) == content_hash(
        normalize_text(extract_main_text(changed))
    )


def test_page_without_article_raises():
    with pytest.raises(MainContentNotFoundError):
        extract_main_text("<html><body><div id=root></div></body></html>")


def test_normalize_ignores_line_edges_newlines_and_blank_lines():
    a = "Статья 1.\n  Текст пункта.\n"
    b = "Статья 1.   \r\n\r\n\tТекст пункта. \r\n\n"
    assert normalize_text(a) == normalize_text(b) == "Статья 1.\nТекст пункта."


def test_normalize_keeps_inner_spaces():
    # Пробелы внутри строки — часть текста, их изменение — настоящее изменение
    assert normalize_text("a  b") != normalize_text("a b")


def test_content_hash_is_sha256_hex():
    h = content_hash("текст")
    assert len(h) == 64
    assert h == content_hash("текст")
    assert h != content_hash("текст.")


def test_extract_title_strips_site_suffix():
    assert extract_title(PAGE) == "Трудовой кодекс Республики Казахстан"
    assert extract_title(PAGE.encode("utf-8")) == "Трудовой кодекс Республики Казахстан"
    assert extract_title("<html></html>") is None
