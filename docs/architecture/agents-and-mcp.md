# Agents and MCP tools

## One workflow, two execution modes

The decision workflow is a CrewAI **Flow** with fixed steps: scope → research → analysis → scenarios → critic
(quality review), with an optional advisory manager. Step state lives in PostgreSQL (`workflow_run`,
`workflow_step`), so a run can be cancelled and resumed without repeating completed steps.

| Mode | Availability | What runs | Output labels |
| --- | --- | --- | --- |
| **Deterministic** | Always, offline | Computed implementations for every role; research retrieves real library passages and writes a templated summary | *Computed* (numbers, checks, retrieval), *Simulated* (templated narrative) |
| **Model-enabled** | Only when the readiness probe to host Ollama passes | The same computed step first, then a real CrewAI `Agent` on the local model interprets and selects | *Model-generated* for the model's text; numbers stay *Computed* |

Model output is validated against Pydantic contracts (`backend/app/modules/agents/contracts.py`). Invalid output
gets one retry, then the computed result is used with a visible note. Each step has a time budget
(`MODEL_STEP_TIMEOUT_SECONDS`); a timeout fails the step with "Completed steps are preserved; resume to retry".
Cancellation closes the model HTTP stream; the step's result is discarded.

Prompts are versioned files (`backend/prompts/<role>.v1.toml`). Each step records the prompt version and the
model name and digest.

## MCP boundary

Agents reach data only through an internal MCP server (`backend/app/modules/mcp_tools/server.py`) that the worker
starts as a **stdio** child process. It has no network listener.

| Tool | Kind |
| --- | --- |
| `rag_search` | Read: library passages with citations |
| `market_get_quotes`, `market_get_history` | Read: Mock quotes and history |
| `calendar_get_events` | Read: venue sessions and events |
| `instrument_lookup` | Read |
| `portfolio_get_positions`, `portfolio_get_exposure` | Read |
| `scenario_run`, `checks_run` | Compute |

There are **no** tools for orders, cancellation, sharing, invitations, settings, approvals or deletion. Every call
carries a capability token issued per run and role (data scope, 20-minute expiry) that the worker injects; the
model never sees or chooses it. Each role has a tool-call budget; calls are logged (`tool_call_log`). CrewAI tool
filters exist only as defence in depth: authorization happens server-side in `dispatch()`.

Agent "suggestions" (follow-up research, an order intent, a share) are stored as inert proposals and shown under
**Suggestions (not executed)**. Nothing happens unless the owner acts through the normal screens.

Retrieved documents are untrusted: they are delimited as data in prompts, cannot trigger consequential tools (none
exist), and the critic flags instruction-like content (injection fixtures in the test suite).

## Known limitation: model tool use

The model-enabled mode uses schema-constrained JSON output with reasoning disabled (CrewAI `LLM` with the
`ollama_chat/` provider, `response_format` = the step's schema, `reasoning_effort="none"`). This was chosen after
measuring on this CPU-only machine: free-form answers from `qwen3:4b` carried 1,000+ tokens of reasoning even with
thinking disabled (~150 s per call), while schema-constrained JSON answers in seconds and keeps the shape. Under
JSON mode the model **seldom calls MCP tools itself**. The evidence it reasons over is gathered by the computed step through the **same MCP gateway**
(same capability tokens, budgets and logs) and placed in the prompt.

Consequence: the MCP boundary and permissions are real and tested, but in model mode the *agent choosing which tool
to call* is rarely exercised. A faster model/host could switch to native tool calling without changing the tool
server or its permissions.

## Verification

- Deterministic path: J3 (Playwright) and integration tests. Status: **Implemented and verified locally**.
- Model path: J4 ran a full model-mode cycle with the real `qwen3:4b` on this machine (cancel mid-run → resume →
  no step succeeded twice; model name, digest and prompt versions recorded). Status: **Implemented and verified
  locally** on the isolated E2E stack. The owner's own instance records its own verification the first time
  model mode is run there (Settings → Integrations shows "Model not run on this machine yet" until then).
