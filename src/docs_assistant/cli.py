"""Командная строка проекта: docs-assistant api | fetch | register."""

import argparse
import asyncio
import logging
import sys
from collections import Counter
from pathlib import Path

from docs_assistant.config import get_settings
from docs_assistant.ingestion.sources import Source, load_sources


def _select(sources: list[Source], only: list[str] | None) -> list[Source]:
    if not only:
        return sources
    wanted = set(only)
    return [s for s in sources if s.external_id in wanted]


async def _fetch(sources_path: Path, only: list[str] | None, force: bool) -> int:
    from docs_assistant.ingestion.fetch_adilet import FetchStatus, fetch_all

    settings = get_settings()
    if not settings.fetch_contact:
        logging.warning("FETCH_CONTACT не задан в .env: в User-Agent не будет контакта")
    sources = _select(load_sources(sources_path), only)
    results = await fetch_all(sources, settings, force=force)
    counts = Counter(r.status for r in results)
    print(", ".join(f"{status}: {n}" for status, n in sorted(counts.items())))
    for r in results:
        if r.status in (FetchStatus.failed, FetchStatus.repealed):
            print(f"  {r.status}: {r.source.url} — {r.error}")
    return 1 if counts[FetchStatus.failed] else 0


async def _register(sources_path: Path, only: list[str] | None) -> int:
    from docs_assistant.infra.db import get_engine, get_sessionmaker
    from docs_assistant.ingestion.registry import register_file

    settings = get_settings()
    sessionmaker = get_sessionmaker()
    counts: Counter[str] = Counter()
    try:
        for source in _select(load_sources(sources_path), only):
            path = settings.raw_dir / source.raw_filename()
            if not path.exists():
                counts["missing"] += 1
                logging.warning("нет файла %s, сначала docs-assistant fetch", path)
                continue
            # Отдельная транзакция на документ: ошибка в одном не откатывает остальные
            async with sessionmaker() as session, session.begin():
                try:
                    result = await register_file(session, source, path)
                except ValueError as exc:
                    counts["failed"] += 1
                    logging.error("%s: %s", path, exc)
                    continue
            counts[result.action] += 1
            logging.info("%s %s v%d", result.action, source.url, result.version)
    finally:
        await get_engine().dispose()
    print(", ".join(f"{action}: {n}" for action, n in sorted(counts.items())) or "нет документов")
    return 1 if counts["failed"] else 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # httpx на уровне INFO логирует каждый запрос — дублирует наш прогресс
    logging.getLogger("httpx").setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(prog="docs-assistant")
    sub = parser.add_subparsers(dest="command", required=True)

    api = sub.add_parser("api", help="запустить HTTP API")
    api.add_argument("--host", default="0.0.0.0")
    api.add_argument("--port", type=int, default=8000)
    api.add_argument("--reload", action="store_true")

    default_sources = get_settings().sources_path
    for name, help_text in [
        ("fetch", "скачать документы из sources.yaml в data/raw"),
        ("register", "зарегистрировать скачанные документы в БД"),
    ]:
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--sources", type=Path, default=default_sources)
        cmd.add_argument("--only", nargs="+", metavar="EXTERNAL_ID", help="только эти коды")
        if name == "fetch":
            cmd.add_argument("--force", action="store_true", help="перекачать существующие файлы")

    args = parser.parse_args()
    if args.command == "api":
        import uvicorn

        uvicorn.run(
            "docs_assistant.api.main:app", host=args.host, port=args.port, reload=args.reload
        )
    elif args.command == "fetch":
        sys.exit(asyncio.run(_fetch(args.sources, args.only, args.force)))
    elif args.command == "register":
        sys.exit(asyncio.run(_register(args.sources, args.only)))


if __name__ == "__main__":
    main()
