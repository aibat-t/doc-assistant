# Docs Assistant (RAG)

Ассистент, который отвечает на вопросы по законодательству Республики Казахстан со ссылками на конкретные статьи. Индексация идёт асинхронно через RabbitMQ, поиск гибридный (pgvector + BM25 + reranker), ответ приходит потоком.

> Статус: этап 1 — корпус и учёт документов. Метрики качества появятся после этапа 6.

## Быстрый старт

Нужны: Docker, [uv](https://docs.astral.sh/uv/). Команды для PowerShell; `make` не обязателен.

```powershell
Copy-Item .env.example .env          # вписать ANTHROPIC_API_KEY и FETCH_CONTACT
uv sync                              # зависимости
docker compose up -d --wait          # Postgres + pgvector, RabbitMQ, Redis
uv run alembic upgrade head          # схема БД
uv run docs-assistant fetch          # скачать документы из data/sources.yaml в data/raw
uv run docs-assistant register       # зарегистрировать их в таблице documents
uv run docs-assistant api --reload   # API на http://localhost:8000
```

Проверка:

```powershell
curl.exe localhost:8000/health/ready
# {"status":"ok","checks":{"postgres":"ok","rabbitmq":"ok","redis":"ok"}}
```

Документация API: http://localhost:8000/docs · RabbitMQ: http://localhost:15672 (rag / rag)

## Команды

| Команда | Что делает |
|---|---|
| `docker compose up -d --wait` / `docker compose down` | Поднять / остановить инфраструктуру |
| `uv run alembic upgrade head` | Применить миграции |
| `uv run alembic revision --autogenerate -m "..."` | Черновик новой миграции по изменённым моделям (проверить глазами) |
| `uv run docs-assistant fetch [--only K1500000414] [--force]` | Скачать документы (без `--force` существующие файлы не перекачиваются) |
| `uv run docs-assistant register [--only ...]` | Создать запись или новую версию, если изменился текст |
| `uv run docs-assistant api --reload` | API с автоперезагрузкой |
| `uv run pytest` | Быстрые тесты без инфраструктуры |
| `uv run pytest -m integration` | Интеграционные тесты (нужен `docker compose up`) |
| `uv run ruff check .` / `uv run ruff format .` | Проверка / автоисправление стиля |
| `uv sync --extra ml` | sentence-transformers и torch (с этапа 3) |

## Корпус

<!-- CORPUS -->

## Структура

```
src/docs_assistant/
├── config.py        # настройки из .env
├── cli.py           # docs-assistant api | fetch | register
├── models.py        # ORM-модели SQLAlchemy
├── infra/db.py      # async-движок и сессии
├── api/             # FastAPI: /health, /health/ready; дальше /documents, /ask
├── ingestion/       # этап 1: sources, fetch_adilet, registry; дальше парсинг, чанкинг, воркер
├── retrieval/       # этапы 3, 7: вектор, BM25, RRF, rerank
├── generation/      # этап 5: промпты, LLM-клиент, цитаты
└── infra/           # БД, очередь, кэш, трейсинг
alembic/             # миграции схемы БД
data/sources.yaml    # список документов корпуса
evals/               # этап 6: тестовые вопросы и отчёты
docs/decisions.md    # журнал архитектурных решений
```

## Архитектурные решения

См. [docs/decisions.md](docs/decisions.md).
