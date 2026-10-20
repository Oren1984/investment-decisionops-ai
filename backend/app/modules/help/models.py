from sqlalchemy import Computed, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class HelpArticle(Base):
    __tablename__ = "help_article"

    slug: Mapped[str] = mapped_column(String(80), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="General")
    routes: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    tsv = mapped_column(TSVECTOR, Computed("to_tsvector('english', title || ' ' || summary || ' ' || body)", persisted=True))

    __table_args__ = (Index("ix_help_tsv", "tsv", postgresql_using="gin"),)
