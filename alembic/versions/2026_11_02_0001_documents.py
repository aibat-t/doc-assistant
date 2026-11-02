"""Таблица documents: учёт документов корпуса, хеш содержимого и версия

Revision ID: 0001
Revises:
Create Date: 2026-11-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

document_status = postgresql.ENUM(
    "queued", "indexing", "indexed", "failed", name="document_status", create_type=False
)


def upgrade() -> None:
    # Тип enum создаём явно, чтобы downgrade мог его так же явно удалить
    document_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("lang", sa.Text(), nullable=False),
        sa.Column("doc_type", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", document_status, nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("raw_path", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("source_url", name=op.f("uq_documents_source_url")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_documents_version_positive")),
    )
    # Воркер и `reindex` будут выбирать документы по статусу
    op.create_index(op.f("ix_documents_status"), "documents", ["status"])


def downgrade() -> None:
    op.drop_index(op.f("ix_documents_status"), table_name="documents")
    op.drop_table("documents")
    document_status.drop(op.get_bind(), checkfirst=True)
