"""Ручная проверка чанкинга: статистика по корпусу и случайные чанки.

    uv run python scripts/inspect_chunks.py                  # весь корпус, 20 чанков
    uv run python scripts/inspect_chunks.py --only K1500000414 --sample 5
    uv run python scripts/inspect_chunks.py --out chunks.txt # в файл (консоль Windows и кириллица)

БД не нужна: документы берутся из data/sources.yaml и data/raw. Идентификаторы документов —
временные (uuid5 от URL), настоящие появятся при индексации на этапе 3.
"""

import argparse
import random
import statistics
import sys
import time
import uuid
from collections import Counter
from pathlib import Path

from docs_assistant.config import get_settings
from docs_assistant.ingestion.chunking import Chunk, DocumentInfo, chunk_document, e5_token_counter
from docs_assistant.ingestion.parsers.html_adilet import parse_document
from docs_assistant.ingestion.sources import load_sources
from docs_assistant.ingestion.text import extract_title


def percentile(values: list[int], q: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="+", metavar="EXTERNAL_ID")
    parser.add_argument("--sample", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, help="записать отчёт в файл (UTF-8)")
    args = parser.parse_args()

    settings = get_settings()
    count = e5_token_counter(settings.embedding_model)
    out = args.out.open("w", encoding="utf-8") if args.out else sys.stdout
    if out is sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    chunks: list[Chunk] = []
    started = time.perf_counter()
    for source in load_sources(settings.sources_path):
        if args.only and source.external_id not in args.only:
            continue
        path = settings.raw_dir / source.raw_filename()
        if not path.exists():
            print(f"нет файла {path}", file=sys.stderr)
            continue
        html = path.read_bytes()
        doc = DocumentInfo(
            id=uuid.uuid5(uuid.NAMESPACE_URL, source.url),
            version=1,
            title=source.title or extract_title(html) or source.external_id,
            lang=source.lang,
            doc_type=source.doc_type or "law",
        )
        doc_chunks = chunk_document(
            parse_document(html),
            doc,
            max_tokens=settings.chunk_size_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
            count=count,
        )
        articles = {c.article_number for c in doc_chunks if c.article_number}
        print(
            f"{source.raw_filename():<22} статей {len(articles):>4}  чанков {len(doc_chunks):>5}",
            file=out,
        )
        chunks.extend(doc_chunks)
    elapsed = time.perf_counter() - started

    if not chunks:
        print("чанков нет", file=out)
        return
    lengths = [count(c.text) for c in chunks]
    over = sum(n > settings.chunk_size_tokens for n in lengths)
    # Сколько статей уложилось в один чанк, а сколько пришлось резать
    per_article = Counter((c.document_id, c.article_number) for c in chunks if c.article_number)
    whole = sum(n == 1 for n in per_article.values())
    print(
        f"\nВсего чанков: {len(chunks)} за {elapsed:.0f} с\n"
        f"Токенов e5 на чанк: медиана {statistics.median(lengths):.0f}, "
        f"p95 {percentile(lengths, 0.95)}, максимум {max(lengths)}, "
        f"лимит {settings.chunk_size_tokens}, превышений {over}\n"
        f"Статей целиком в одном чанке: {whole} из {len(per_article)} "
        f"({whole / len(per_article):.0%})",
        file=out,
    )

    rng = random.Random(args.seed)
    for c in rng.sample(chunks, min(args.sample, len(chunks))):
        print(
            f"\n--- {c.lang} · статья {c.article_number} · чанк {c.chunk_index} · "
            f"{count(c.text)} токенов\n{c.text}",
            file=out,
        )


if __name__ == "__main__":
    main()
