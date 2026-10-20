import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DB

from app.config import get_settings
from app.core import audit
from app.core.authz import Principal, perm, require_step_up
from app.core.db import get_db
from app.core.errors import AppError, NotFound
from app.modules.knowledge import answers, deletion, embeddings
from app.modules.knowledge.ingest import store_upload
from app.modules.knowledge.models import Chunk, Document
from app.modules.workflows.jobs import enqueue

router = APIRouter(prefix="/api/library", tags=["library"])


def doc_out(d: Document) -> dict:
    return {"id": str(d.id), "title": d.title, "filename": d.filename, "file_type": d.file_type,
            "size_bytes": d.size_bytes, "pages": d.pages, "status": d.status, "error": d.error,
            "chunk_count": d.chunk_count, "embedding_model": d.embedding_model, "created_at": d.created_at,
            "indexed_at": d.indexed_at}


@router.get("/status")
def library_status(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:library"))):
    s = get_settings()
    used = db.scalar(select(func.coalesce(func.sum(Document.size_bytes), 0)))
    return {"embeddings": embeddings.status() if embeddings.enabled() else
            {"enabled": False, "state": "disabled", "message": "Keyword search only (embeddings disabled)."},
            "quota_bytes": s.library_quota_bytes, "used_bytes": used, "max_file_bytes": s.upload_max_bytes,
            "max_pages": s.upload_max_pages, "allowed_types": ["pdf", "md", "txt", "csv"],
            "documents": db.scalar(select(func.count()).select_from(Document))}


@router.get("/documents")
def list_documents(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:library"))):
    return [doc_out(d) for d in db.scalars(select(Document).order_by(Document.created_at.desc()))]


@router.post("/documents")
async def upload(file: UploadFile = File(...), title: str | None = Form(None), db: DB = Depends(get_db, scope="function"),
                 principal: Principal = Depends(perm("write:library"))):
    data = await file.read(get_settings().upload_max_bytes + 1)
    doc = store_upload(db, principal.user_id, file.filename or "document", title, data)
    audit.record(db, "library.document_uploaded", actor=principal, object_type="document", object_id=doc.id,
                 details={"size_bytes": doc.size_bytes, "file_type": doc.file_type})
    return doc_out(doc)


@router.get("/documents/{document_id}")
def get_document(document_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:library"))):
    d = db.get(Document, document_id)
    if d is None:
        raise NotFound("Document")
    chunks = db.scalars(select(Chunk).where(Chunk.document_id == d.id).order_by(Chunk.ordinal).limit(200))
    return {**doc_out(d), "chunks": [{"id": str(c.id), "ordinal": c.ordinal, "page": c.page, "section": c.section,
                                      "text": c.text, "embedded": c.embedding_model is not None} for c in chunks]}


@router.post("/documents/{document_id}/reindex")
def reindex(document_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:library"))):
    d = db.get(Document, document_id)
    if d is None:
        raise NotFound("Document")
    d.status = "uploaded"
    enqueue(db, "ingest_document", {"document_id": str(d.id)}, dedupe_key=f"ingest:{d.id}")
    audit.record(db, "library.reindex", actor=principal, object_type="document", object_id=d.id)
    return doc_out(d)


@router.post("/reindex")
def reindex_all(db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:library"))):
    count = 0
    for d in db.scalars(select(Document)):
        d.status = "uploaded"
        enqueue(db, "ingest_document", {"document_id": str(d.id)}, dedupe_key=f"ingest:{d.id}")
        count += 1
    audit.record(db, "library.reindex_all", actor=principal, details={"documents": count})
    return {"queued": count}


@router.get("/documents/{document_id}/deletion-preview")
def deletion_preview(document_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:library"))):
    d = db.get(Document, document_id)
    if d is None:
        raise NotFound("Document")
    return {**deletion.preview(db, d), "erase_phrase": deletion.ERASE_PHRASE}


class DeleteIn(BaseModel):
    mode: Literal["remove", "erase"]
    confirm_phrase: str | None = None


@router.post("/documents/{document_id}/delete")
def delete_document(document_id: uuid.UUID, body: DeleteIn, db: DB = Depends(get_db, scope="function"),
                    principal: Principal = Depends(perm("write:library"))):
    d = db.get(Document, document_id)
    if d is None:
        raise NotFound("Document")
    if body.mode == "erase":
        require_step_up(principal)
        if (body.confirm_phrase or "").strip() != deletion.ERASE_PHRASE:
            raise AppError("confirmation_required", f"Type {deletion.ERASE_PHRASE} to confirm full erasure.",
                           status_code=422, help_slug="knowledge-library")
        result = deletion.erase(db, principal, d)
    else:
        result = deletion.remove_from_library(db, principal, d)
    return {"ok": True, "mode": body.mode, **result}


@router.get("/ask")
def ask(q: str = Query(min_length=3, max_length=1000), use_model: bool = False, db: DB = Depends(get_db, scope="function"),
        principal: Principal = Depends(perm("read:library"))):
    if use_model and principal.is_demo:
        use_model = False  # the demo shows deterministic answers only
    return answers.answer(db, principal, q, use_model=use_model)
