from pathlib import Path

import pytest
from pydantic import ValidationError

from docs_assistant.ingestion.sources import Source, load_sources

TK_URL = "https://adilet.zan.kz/rus/docs/K1500000414"


def test_source_derived_fields():
    s = Source(url=TK_URL, lang="ru")
    assert s.external_id == "K1500000414"
    assert s.doc_type == "code"
    assert s.raw_filename() == "K1500000414_ru.html"
    assert s.fetch_url("https://old.adilet.zan.kz/") == TK_URL.replace("adilet", "old.adilet")


def test_kazakh_source_uses_kaz_path():
    s = Source(url="https://adilet.zan.kz/kaz/docs/Z1300000094", lang="kk")
    assert s.doc_type == "law"
    assert s.raw_filename() == "Z1300000094_kk.html"
    assert (
        s.fetch_url("https://old.adilet.zan.kz") == "https://old.adilet.zan.kz/kaz/docs/Z1300000094"
    )


def test_explicit_doc_type_is_kept():
    assert Source(url=TK_URL, lang="ru", doc_type="law").doc_type == "law"


@pytest.mark.parametrize(
    "url, lang",
    [
        (TK_URL, "kk"),  # язык не совпадает с путём
        ("https://example.com/rus/docs/K1500000414", "ru"),
        ("https://adilet.zan.kz/rus/docs/K1500000414?x=1", "ru"),
    ],
)
def test_invalid_source(url, lang):
    with pytest.raises(ValidationError):
        Source(url=url, lang=lang)


def test_load_sources_rejects_duplicates(tmp_path: Path):
    path = tmp_path / "sources.yaml"
    path.write_text(
        f"documents:\n  - {{url: '{TK_URL}', lang: ru}}\n  - {{url: '{TK_URL}', lang: ru}}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="повторяющиеся"):
        load_sources(path)


def test_project_sources_file_is_valid():
    sources = load_sources(Path("data/sources.yaml"))
    assert len(sources) >= 8
