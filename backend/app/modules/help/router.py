from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, literal, select, text
from sqlalchemy.orm import Session as DB

from app.core.authz import perm
from app.core.db import get_db
from app.core.errors import NotFound
from app.modules.help.models import HelpArticle

router = APIRouter(prefix="/api/help", tags=["help"])


@router.get("")
def list_articles(db: DB = Depends(get_db, scope="function"), _=Depends(perm("public"))):
    rows = db.scalars(select(HelpArticle).order_by(HelpArticle.category, HelpArticle.title))
    return [{"slug": a.slug, "title": a.title, "summary": a.summary, "category": a.category, "routes": a.routes}
            for a in rows]


@router.get("/search")
def search(q: str = Query(min_length=2, max_length=200), db: DB = Depends(get_db, scope="function"), _=Depends(perm("public"))):
    query = func.websearch_to_tsquery("english", q)
    rows = db.execute(
        select(HelpArticle.slug, HelpArticle.title, HelpArticle.summary, HelpArticle.category,
               func.ts_rank_cd(HelpArticle.tsv, query).label("rank"),
               func.ts_headline("english", HelpArticle.body, query,
                                text("'MaxFragments=1, MaxWords=25, MinWords=8, StartSel=«, StopSel=»'")).label("snippet"))
        .where(HelpArticle.tsv.op("@@")(query)).order_by(text("rank DESC")).limit(15)).all()
    if not rows:  # fall back to a simple title match
        rows = db.execute(select(HelpArticle.slug, HelpArticle.title, HelpArticle.summary, HelpArticle.category,
                                 literal(0).label("rank"), HelpArticle.summary.label("snippet"))
                          .where(HelpArticle.title.ilike(f"%{q}%")).limit(15)).all()
    return [{"slug": r.slug, "title": r.title, "summary": r.summary, "category": r.category, "snippet": r.snippet}
            for r in rows]


@router.get("/{slug}")
def article(slug: str, db: DB = Depends(get_db, scope="function"), _=Depends(perm("public"))):
    a = db.get(HelpArticle, slug)
    if a is None:
        raise NotFound("Help article")
    return {"slug": a.slug, "title": a.title, "summary": a.summary, "category": a.category, "routes": a.routes,
            "body": a.body}
