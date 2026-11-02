"""Настройки приложения. Все значения читаются из переменных окружения или файла .env."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Инфраструктура
    database_url: str = "postgresql+asyncpg://rag:rag@localhost:5432/rag"
    rabbitmq_url: str = "amqp://rag:rag@localhost:5672/"
    redis_url: str = "redis://localhost:6379/0"
    index_queue: str = "documents.index"

    # Корпус документов
    sources_path: Path = Path("data/sources.yaml")
    raw_dir: Path = Path("data/raw")
    # Новый adilet.zan.kz — SPA, текст закона в HTML не приходит (его подгружает JS через API
    # с ключом). Старый портал отдаёт готовый HTML, поэтому качаем оттуда. Каноническим URL
    # документа остаётся https://adilet.zan.kz/... — его и показываем в цитатах.
    fetch_base_url: str = "https://old.adilet.zan.kz"
    # Контакт в User-Agent, чтобы администраторы сайта могли связаться (e-mail или URL репозитория)
    fetch_contact: str = ""
    fetch_delay_s: float = 1.0
    # Кодексы весят 1–3 МБ, и старый портал отдаёт их медленно
    fetch_timeout_s: float = 180.0
    fetch_retries: int = 3

    # LLM: основная и резервная модель
    anthropic_api_key: SecretStr = SecretStr("")
    llm_primary_model: str = "claude-sonnet-5-5"
    llm_fallback_model: str = "claude-haiku-5-5"
    llm_timeout_s: float = 30.0
    llm_max_retries: int = 3

    # Эмбеддинги (локально, sentence-transformers)
    embedding_model: str = "intfloat/multilingual-e5-large"
    embedding_dim: int = 1024
    embedding_batch_size: int = 32

    # Чанкинг и поиск
    chunk_size_tokens: int = 400
    chunk_overlap_tokens: int = 50
    retrieval_candidates: int = 30
    retrieval_top_k: int = 5
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    # Кэш
    answer_cache_ttl_s: int = 24 * 3600


@lru_cache
def get_settings() -> Settings:
    return Settings()
