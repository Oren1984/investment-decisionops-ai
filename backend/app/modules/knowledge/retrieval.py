"""Access-scoped retrieval. The principal filter is applied in SQL, never after the fact."""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.authz import Principal, granted_object_ids
from app.modules.knowledge import embeddings

ABSTAIN_MIN_COVERAGE = 0.4
ABSTAIN_MIN_SIMILARITY = 0.78
RRF_K = 60


@dataclass
class Hit:
    chunk_id: str
    document_id: str
    document_title: str
    text: str
    page: int | None
    section: str | None
    fts_rank: float
    coverage: float
    similarity: float | None
    score: float

    def location(self) -> str:
        parts = []
        if self.page:
            parts.append(f"p. {self.page}")
        if self.section:
            parts.append(f"§ {self.section}")
        return ", ".join(parts) or "whole document"

    def as_dict(self) -> dict:
        return {"chunk_id": self.chunk_id, "document_id": self.document_id, "document_title": self.document_title,
                "text": self.text, "page": self.page, "section": self.section, "location": self.location(),
                "fts_rank": round(self.fts_rank, 5), "coverage": round(self.coverage, 3),
                "similarity": None if self.similarity is None else round(self.similarity, 4),
                "score": round(self.score, 5)}


def _scope(db: Session, principal: Principal) -> tuple[bool, list[str]]:
    if principal.sees_owner_data:
        return True, []
    return False, [str(i) for i in granted_object_ids(db, principal, "document")]


def query_lexemes(db: Session, query: str) -> list[str]:
    rows = db.execute(text("SELECT lexeme FROM unnest(to_tsvector('english', :q)) ORDER BY lexeme"), {"q": query})
    return [r[0] for r in rows]


def search(db: Session, principal: Principal, query: str, k: int = 5,
           document_ids: list[uuid.UUID] | None = None) -> tuple[list[Hit], dict]:
    all_docs, granted = _scope(db, principal)
    lexemes = query_lexemes(db, query)
    meta = {"method": "fts", "lexemes": lexemes, "embeddings": embeddings.status()["state"]}
    if not lexemes and not embeddings.enabled():
        return [], meta
    doc_filter = [str(d) for d in document_ids] if document_ids else None
    params = {"all_docs": all_docs, "granted": granted, "doc_filter": doc_filter, "lexemes": lexemes,
              "n": len(lexemes) or 1, "limit": max(k * 4, 20)}
    scope_sql = """
        d.status = 'ready'
        AND (:all_docs OR d.id = ANY(CAST(:granted AS uuid[])))
        AND (CAST(:doc_filter AS uuid[]) IS NULL OR d.id = ANY(CAST(:doc_filter AS uuid[])))
    """
    fts_rows = []
    if lexemes:
        fts_rows = db.execute(text(f"""
            WITH q AS (
                SELECT to_tsquery('simple', string_agg(quote_literal(l), ' | ')) AS query
                FROM unnest(CAST(:lexemes AS text[])) AS l
            )
            SELECT c.id, c.document_id, d.title, c.text, c.page, c.section,
                   ts_rank_cd(c.tsv, q.query, 32) AS rank,
                   (SELECT count(*) FROM unnest(CAST(:lexemes AS text[])) AS l
                     WHERE c.tsv @@ to_tsquery('simple', quote_literal(l)))::float / :n AS coverage
            FROM chunk c JOIN document d ON d.id = c.document_id, q
            WHERE c.tsv @@ q.query AND {scope_sql}
            ORDER BY coverage DESC, rank DESC
            LIMIT :limit
        """), params).all()

    vec_rows = []
    if embeddings.enabled():
        try:
            qvec = embeddings.embed([query])[0]
            meta["method"] = "hybrid"
            vec_rows = db.execute(text(f"""
                SELECT c.id, c.document_id, d.title, c.text, c.page, c.section,
                       1 - (c.embedding <=> CAST(:qvec AS vector)) AS similarity
                FROM chunk c JOIN document d ON d.id = c.document_id
                WHERE c.embedding IS NOT NULL AND {scope_sql}
                ORDER BY c.embedding <=> CAST(:qvec AS vector)
                LIMIT :limit
            """), {**params, "qvec": str(qvec)}).all()
        except Exception:  # noqa: BLE001 - fall back to keyword search
            meta["method"] = "fts"
            meta["embeddings"] = "unavailable"

    hits: dict[str, Hit] = {}
    for rank_pos, r in enumerate(fts_rows):
        hits[str(r.id)] = Hit(str(r.id), str(r.document_id), r.title, r.text, r.page, r.section,
                              float(r.rank), float(r.coverage), None, 1 / (RRF_K + rank_pos + 1))
    for rank_pos, r in enumerate(vec_rows):
        key = str(r.id)
        rrf = 1 / (RRF_K + rank_pos + 1)
        if key in hits:
            hits[key].similarity = float(r.similarity)
            hits[key].score += rrf
        else:
            hits[key] = Hit(key, str(r.document_id), r.title, r.text, r.page, r.section, 0.0, 0.0,
                            float(r.similarity), rrf)
    ordered = sorted(hits.values(), key=lambda h: (-h.score, -h.coverage))
    return ordered[:k], meta


def should_abstain(hits: list[Hit]) -> bool:
    if not hits:
        return True
    best_cov = max(h.coverage for h in hits)
    best_sim = max((h.similarity or 0.0) for h in hits)
    return best_cov < ABSTAIN_MIN_COVERAGE and best_sim < ABSTAIN_MIN_SIMILARITY
