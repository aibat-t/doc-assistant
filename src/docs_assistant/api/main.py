"""Точка входа HTTP API. Эндпоинты /documents и /ask появятся на этапах 4–5."""

from fastapi import FastAPI

from docs_assistant import __version__
from docs_assistant.api.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title="Docs Assistant (RAG)", version=__version__)
    app.include_router(health_router)
    return app


app = create_app()
