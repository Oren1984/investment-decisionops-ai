import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Computed, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.types import TS, UUIDT, created_at, uuid_pk

EMBEDDING_DIM = 384


class Document(Base):
    __tablename__ = "document"

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    filename: Mapped[str] = mapped_column(String(200), nullable=False)  # sanitized
    file_type: Mapped[str] = mapped_column(String(8), nullable=False)  # pdf | md | txt | csv
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pages: Mapped[int | None] = mapped_column(Integer)
    storage_id: Mapped[str] = mapped_column(String(64), nullable=False)  # random name in the uploads volume
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="uploaded")
    # uploaded | parsing | ready | failed
    error: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding_model: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = created_at()
    indexed_at: Mapped[datetime | None] = mapped_column(TS)


class Chunk(Base):
    __tablename__ = "chunk"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("document.id", ondelete="CASCADE"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(200))
    doc_title: Mapped[str | None] = mapped_column(String(200))  # indexed with the chunk so titles are searchable
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    tsv = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', coalesce(doc_title, '') || ' ' || coalesce(section, '') || ' ' || text)",
                 persisted=True)
    )
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(80))

    __table_args__ = (
        Index("ix_chunk_document", "document_id"),
        Index("ix_chunk_tsv", "tsv", postgresql_using="gin"),
        Index("ix_chunk_embedding", "embedding", postgresql_using="hnsw",
              postgresql_ops={"embedding": "vector_cosine_ops"}),
    )


class AnswerHistory(Base):
    """Answers given to library questions (a derived copy of document text; erased on full erasure)."""

    __tablename__ = "answer_history"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(12), nullable=False)  # extractive | generated | abstained
    answer: Mapped[dict] = mapped_column(JSONB, nullable=False)
    document_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    created_at: Mapped[datetime] = created_at()
