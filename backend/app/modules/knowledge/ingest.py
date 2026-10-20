"""Safe upload and ingestion: allowlist + magic bytes, size/quota caps, random storage IDs in a non-served
volume, parsing in a subprocess with timeout and memory limit."""

import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.clock import utcnow
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.security import new_token
from app.modules.knowledge import embeddings
from app.modules.knowledge.models import Chunk, Document
from app.modules.knowledge.text import chunk_pages
from app.modules.workflows.jobs import enqueue

log = get_logger("knowledge")

ALLOWED = {".pdf": "pdf", ".md": "md", ".markdown": "md", ".txt": "txt", ".csv": "csv"}


def uploads_dir() -> Path:
    path = get_settings().data_dir / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def sanitize_filename(name: str) -> str:
    name = Path(name).name  # drop any path components (traversal)
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .")
    return (name or "document")[:200]


def detect_type(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED:
        raise AppError("file_type_not_allowed", "Only PDF (text-based), Markdown, plain text and CSV files are "
                       "supported.", status_code=415, help_slug="knowledge-library")
    kind = ALLOWED[ext]
    if kind == "pdf":
        if not data.startswith(b"%PDF-"):
            raise AppError("file_content_mismatch", "The file does not look like a PDF.", status_code=415,
                           help_slug="knowledge-library")
    else:
        if b"\x00" in data[:8192]:
            raise AppError("file_content_mismatch", "Text files must not contain binary data.", status_code=415,
                           help_slug="knowledge-library")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AppError("file_encoding", "Text files must be UTF-8 encoded.", status_code=415,
                           help_slug="knowledge-library") from exc
    return kind


def store_upload(db: Session, owner_id: uuid.UUID, filename: str, title: str | None, data: bytes) -> Document:
    settings = get_settings()
    if len(data) == 0:
        raise AppError("empty_file", "The file is empty.", status_code=422)
    if len(data) > settings.upload_max_bytes:
        raise AppError("file_too_large", f"Files are limited to {settings.upload_max_bytes // (1024 * 1024)} MB.",
                       status_code=413, help_slug="knowledge-library")
    used = db.scalar(select(func.coalesce(func.sum(Document.size_bytes), 0)))
    if used + len(data) > settings.library_quota_bytes:
        raise AppError("quota_exceeded", "The library quota (2 GB) would be exceeded. Delete documents first.",
                       status_code=413, help_slug="knowledge-library")
    kind = detect_type(filename, data)
    safe = sanitize_filename(filename)
    storage_id = new_token(18)
    (uploads_dir() / storage_id).write_bytes(data)
    doc = Document(owner_id=owner_id, title=(title or Path(safe).stem)[:200], filename=safe, file_type=kind,
                   size_bytes=len(data), storage_id=storage_id, status="uploaded")
    db.add(doc)
    db.flush()
    enqueue(db, "ingest_document", {"document_id": str(doc.id)})
    return doc


def run_parser(path: Path, file_type: str) -> list[dict]:
    settings = get_settings()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "app.modules.knowledge.parse_worker", str(path), file_type,
             str(settings.upload_max_pages)],
            capture_output=True, timeout=settings.parse_timeout_seconds, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Parsing took too long and was stopped. Try a smaller file.") from exc
    if proc.returncode != 0 and not proc.stdout:
        raise ValueError("The parser stopped unexpectedly (the file may be too complex or too large).")
    result = json.loads(proc.stdout.decode() or "{}")
    if "error" in result:
        raise ValueError(result["error"])
    return result.get("pages", [])


def ingest(db: Session, document_id: uuid.UUID) -> None:
    doc = db.get(Document, document_id)
    if doc is None:
        return  # deleted meanwhile
    doc.status = "parsing"
    db.flush()
    path = uploads_dir() / doc.storage_id
    try:
        pages = run_parser(path, doc.file_type)
        chunks = chunk_pages(pages)
        if not chunks:
            raise ValueError("No readable text was found in this file.")
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        doc.status, doc.error = "failed", str(exc)[:500]
        log.info("ingest_failed", document_id=str(doc.id))
        return
    db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    vectors: list | None = None
    model_name = None
    if embeddings.enabled():
        try:
            vectors = embeddings.embed([c["text"] for c in chunks])
            model_name = get_settings().embedding_model
        except Exception as exc:  # noqa: BLE001 - keyword search still works
            log.warning("embedding_failed", document_id=str(doc.id), error=str(exc)[:200])
    for i, c in enumerate(chunks):
        db.add(Chunk(document_id=doc.id, ordinal=i, text=c["text"], page=c["page"], section=c["section"],
                     doc_title=doc.title.replace("[Sample] ", ""), token_count=c["token_count"], embedding=vectors[i] if vectors else None,
                     embedding_model=model_name))
    doc.pages = max((p["page"] or 0 for p in pages), default=0) or None
    doc.status, doc.error, doc.chunk_count = "ready", None, len(chunks)
    doc.embedding_model, doc.indexed_at = model_name, utcnow()
    log.info("ingest_done", document_id=str(doc.id), chunks=len(chunks))


def ingest_text(db: Session, owner_id: uuid.UUID | None, title: str, filename: str, text: str) -> Document:
    """Seed helper: store and index a synthetic text/markdown document synchronously."""
    data = text.encode()
    kind = detect_type(filename, data)
    storage_id = new_token(18)
    (uploads_dir() / storage_id).write_bytes(data)
    doc = Document(owner_id=owner_id, title=title, filename=sanitize_filename(filename), file_type=kind,
                   size_bytes=len(data), storage_id=storage_id, status="uploaded")
    db.add(doc)
    db.flush()
    ingest(db, doc.id)
    return doc
