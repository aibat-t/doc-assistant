.PHONY: install install-ml up down logs ps api test test-int lint fmt check

install:            ## зависимости + dev-инструменты + pre-commit хук
	uv sync
	uv run pre-commit install

install-ml:         ## sentence-transformers и torch (нужно с этапа 3)
	uv sync --extra ml

up:                 ## поднять Postgres, RabbitMQ, Redis
	docker compose up -d --wait

down:
	docker compose down

logs:
	docker compose logs -f

ps:
	docker compose ps

api:                ## запустить API с автоперезагрузкой
	uv run docs-assistant api --reload

test:               ## быстрые тесты без инфраструктуры
	uv run pytest

test-int:           ## интеграционные тесты (нужен make up)
	uv run pytest -m integration

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff check --fix .
	uv run ruff format .

check: lint test    ## всё, что гоняет CI
