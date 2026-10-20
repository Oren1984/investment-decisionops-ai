---
title: Setting up the optional local model
category: Setup
summary: Use Ollama on the host for model-enabled runs.
routes: /settings
---
The model is optional. Everything works without it.

1. Install Ollama on the host. On Windows with an Intel GPU it runs natively, **not** in Docker.
2. Pull the default model: `ollama pull qwen3:4b` (about 2.5 GB, Apache-2.0).
3. Keep `OLLAMA_BASE_URL=http://host.docker.internal:11434` and `MODEL_NAME=qwen3:4b` in `.env`, then `docker compose up -d`.
4. Open a decision → Agent runs: **Run with local model** becomes available when the readiness probe passes.

If the model is unavailable, model mode is not offered and the reason is shown. Step timeouts default to 300 seconds (`MODEL_STEP_TIMEOUT_SECONDS`). On CPU, a full model run can take several minutes.
