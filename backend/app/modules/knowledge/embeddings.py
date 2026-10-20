"""Optional local embeddings (fastembed, ONNX on CPU). Independent of the chat model.

With EMBEDDINGS_ENABLED=false (default) nothing is downloaded and retrieval is keyword-only (Postgres FTS).
"""

from functools import lru_cache
from pathlib import Path

from app.config import get_settings
from app.core.logging import get_logger

log = get_logger("embeddings")


def enabled() -> bool:
    return get_settings().embeddings_enabled


def cache_dir() -> Path:
    return get_settings().data_dir / "models" / "fastembed"


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding  # imported lazily: optional dependency

    cache_dir().mkdir(parents=True, exist_ok=True)
    return TextEmbedding(model_name=get_settings().embedding_model, cache_dir=str(cache_dir()))


def embed(texts: list[str]) -> list[list[float]]:
    return [list(map(float, v)) for v in _model().embed(texts)]


def status() -> dict:
    if not enabled():
        return {"enabled": False, "state": "disabled", "message": "Keyword search only (embeddings disabled)."}
    try:
        _model()
        return {"enabled": True, "state": "ready", "model": get_settings().embedding_model}
    except Exception as exc:  # noqa: BLE001
        log.warning("embeddings_unavailable", error=str(exc)[:200])
        return {"enabled": True, "state": "unavailable", "model": get_settings().embedding_model,
                "message": "Embedding model unavailable (first use needs a one-time download). Using keyword search."}
