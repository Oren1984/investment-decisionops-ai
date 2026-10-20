"""Help Center: Markdown articles from help/, indexed into Postgres full-text search."""

import re
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import get_settings
from app.modules.help.models import HelpArticle

_FRONT = re.compile(r"^---\n(.*?)\n---\n", re.S)


def parse_article(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    meta: dict = {"slug": path.stem, "title": path.stem, "summary": "", "category": "General", "routes": []}
    m = _FRONT.match(text)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                k, v = k.strip(), v.strip()
                meta[k] = [r.strip() for r in v.split(",") if r.strip()] if k == "routes" else v
        text = text[m.end():]
    meta["body"] = text.strip()
    return meta


def load_articles(directory: Path | None = None) -> list[dict]:
    directory = directory or get_settings().help_dir
    return [parse_article(p) for p in sorted(directory.glob("*.md"))]


def index_articles(db: Session) -> int:
    articles = load_articles()
    db.execute(delete(HelpArticle))
    for a in articles:
        db.add(HelpArticle(slug=a["slug"], title=a["title"], summary=a["summary"], body=a["body"],
                           category=a["category"], routes=a["routes"]))
    db.flush()
    return len(articles)
