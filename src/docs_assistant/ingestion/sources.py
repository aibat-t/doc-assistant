"""Список документов корпуса (`data/sources.yaml`) и правила построения путей и URL."""

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, model_validator

Lang = Literal["ru", "kk"]
DocType = Literal["code", "law", "decree"]

# На adilet язык закодирован в пути: /rus/docs/... и /kaz/docs/...
LANG_TO_PATH: dict[str, str] = {"ru": "rus", "kk": "kaz"}
PATH_TO_LANG: dict[str, str] = {v: k for k, v in LANG_TO_PATH.items()}

# Канонический URL: https://adilet.zan.kz/rus/docs/K1500000414
_ADILET_URL = re.compile(r"^https://adilet\.zan\.kz/(rus|kaz)/docs/([A-Za-z0-9_]+)$")

# Первая буква кода документа на adilet: K — кодекс, Z — закон, U/P/V — указы и постановления
_DOC_TYPE_BY_PREFIX: dict[str, DocType] = {"K": "code", "Z": "law"}


class Source(BaseModel):
    url: str
    lang: Lang
    doc_type: DocType | None = None  # по умолчанию выводится из кода документа
    title: str | None = None  # по умолчанию берётся из <title> страницы

    @model_validator(mode="after")
    def _check(self) -> "Source":
        m = _ADILET_URL.match(self.url)
        if m is None:
            raise ValueError(
                f"ожидается URL вида https://adilet.zan.kz/rus/docs/<код>, получено {self.url!r}"
            )
        if PATH_TO_LANG[m.group(1)] != self.lang:
            raise ValueError(f"lang={self.lang!r} не совпадает с языком в URL {self.url!r}")
        if self.doc_type is None:
            self.doc_type = _DOC_TYPE_BY_PREFIX.get(self.external_id[0], "decree")
        return self

    @property
    def external_id(self) -> str:
        return self.url.rsplit("/", 1)[1]

    def raw_filename(self) -> str:
        return f"{self.external_id}_{self.lang}.html"

    def fetch_url(self, base_url: str) -> str:
        """URL для скачивания: тот же путь, но на сервере, который отдаёт готовый HTML."""
        return f"{base_url.rstrip('/')}/{LANG_TO_PATH[self.lang]}/docs/{self.external_id}"


def load_sources(path: Path) -> list[Source]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = [Source.model_validate(item) for item in data.get("documents", [])]
    urls = [s.url for s in sources]
    duplicates = sorted({u for u in urls if urls.count(u) > 1})
    if duplicates:
        raise ValueError(f"повторяющиеся документы в {path}: {duplicates}")
    return sources
