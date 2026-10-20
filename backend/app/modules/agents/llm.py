"""Optional local chat model through host-native Ollama. Readiness probe, streaming generation with cooperative
cancellation (the HTTP stream is closed when cancel is requested) and per-call timeouts."""

import json
import time
from collections.abc import Callable

import httpx

from app.config import get_settings
from app.core.logging import get_logger

log = get_logger("llm")


class ModelUnavailable(Exception):
    pass


class GenerationCancelled(Exception):
    pass


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: float, num_ctx: int):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.num_ctx = num_ctx

    def tags(self) -> list[dict]:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=3)
            r.raise_for_status()
            return r.json().get("models", [])
        except (httpx.HTTPError, ValueError) as exc:
            raise ModelUnavailable(f"Ollama is not reachable at {self.base_url}") from exc

    def model_digest(self) -> str:
        for m in self.tags():
            if m.get("name") == self.model or m.get("model") == self.model:
                return m.get("digest", "unknown")
        raise ModelUnavailable(f"Model '{self.model}' is not installed in Ollama (run: ollama pull {self.model})")

    def probe(self, *, generate: bool = True) -> dict:
        started = time.monotonic()
        digest = self.model_digest()
        if generate:
            text, _ = self.generate("Reply with the single word: ready", max_tokens=8, timeout=60)
            if not text.strip():
                raise ModelUnavailable("The model returned an empty response")
        return {"model": self.model, "digest": digest, "latency_ms": int((time.monotonic() - started) * 1000)}

    def generate(self, prompt: str, *, system: str | None = None, max_tokens: int = 800, json_format: bool = False,
                 cancel_check: Callable[[], bool] | None = None, timeout: float | None = None) -> tuple[str, dict]:
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        body: dict = {"model": self.model, "messages": messages, "stream": True,
                      "options": {"num_ctx": self.num_ctx, "num_predict": max_tokens, "temperature": 0.2}}
        if json_format:
            body["format"] = "json"
        if self.model.startswith("qwen3"):
            body["think"] = False
        started = time.monotonic()
        deadline = started + (timeout or self.timeout)
        parts: list[str] = []
        stats: dict = {}
        try:
            with httpx.stream("POST", f"{self.base_url}/api/chat", json=body,
                              timeout=httpx.Timeout(timeout or self.timeout, connect=5)) as resp:
                if resp.status_code != 200:
                    raise ModelUnavailable(f"Ollama returned HTTP {resp.status_code}")
                for line in resp.iter_lines():
                    if cancel_check and cancel_check():
                        raise GenerationCancelled()
                    if time.monotonic() > deadline:
                        raise TimeoutError("Model step exceeded its time budget")
                    if not line:
                        continue
                    chunk = json.loads(line)
                    parts.append(chunk.get("message", {}).get("content", ""))
                    if chunk.get("done"):
                        stats = chunk
                        break
        except httpx.TimeoutException as exc:
            raise TimeoutError("Model step exceeded its time budget") from exc
        except httpx.HTTPError as exc:
            raise ModelUnavailable(f"Model call failed: {exc.__class__.__name__}") from exc
        info = {"model": self.model, "tokens_in": stats.get("prompt_eval_count"),
                "tokens_out": stats.get("eval_count"), "duration_ms": int((time.monotonic() - started) * 1000)}
        return "".join(parts), info


def get_client() -> OllamaClient:
    s = get_settings()
    return OllamaClient(s.ollama_base_url, s.model_name, s.model_step_timeout_seconds, s.model_num_ctx)


_probe_cache: dict = {"at": 0.0, "result": None}


def readiness(max_age: float = 60, generate: bool = True) -> dict:
    """Cached readiness probe used to gate model mode."""
    now = time.monotonic()
    if _probe_cache["result"] is not None and now - _probe_cache["at"] < max_age:
        return _probe_cache["result"]
    client = get_client()
    try:
        info = client.probe(generate=generate)
        result = {"ready": True, **info, "base_url": client.base_url}
    except (ModelUnavailable, TimeoutError) as exc:
        result = {"ready": False, "model": client.model, "base_url": client.base_url, "reason": str(exc)}
    _probe_cache.update(at=now, result=result)
    return result
