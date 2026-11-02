"""ORM-модели SQLAlchemy 2.0.

Схема БД меняется только миграциями Alembic (`alembic/versions`), а не через `create_all`.
Модели нужны для запросов из кода и для `alembic revision --autogenerate`.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import CHAR, CheckConstraint, DateTime, Enum, Integer, MetaData, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Явные имена ограничений и индексов: иначе Postgres придумает свои,
# и последующие миграции (drop/alter constraint) будет сложно написать.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class DocumentStatus(enum.StrEnum):
    queued = "queued"  # зарегистрирован или изменился, ждёт индексации
    indexing = "indexing"  # воркер обрабатывает (этап 4)
    indexed = "indexed"  # чанки и эмбеддинги в БД
    failed = "failed"  # индексация упала, текст ошибки в `error`


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (CheckConstraint("version >= 1", name="version_positive"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Канонический URL — естественный ключ документа: по нему регистратор ищет существующую запись
    source_url: Mapped[str] = mapped_column(Text, unique=True)
    external_id: Mapped[str] = mapped_column(Text)  # код на adilet, например K1500000414
    title: Mapped[str] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(Text)  # ru | kk
    doc_type: Mapped[str] = mapped_column(Text)  # code | law | decree
    # SHA-256 нормализованного текста, 64 hex-символа
    content_hash: Mapped[str] = mapped_column(CHAR(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status"), default=DocumentStatus.queued, index=True
    )
    error: Mapped[str | None] = mapped_column(Text)
    raw_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"Document({self.external_id!r}, lang={self.lang!r}, v{self.version}, {self.status})"
