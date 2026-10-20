---
title: Mock, Paper and Live modes
category: Start
summary: What each trading mode means and why Live is disabled.
routes: /settings
---
The mode badge in the header always shows where orders would go.

| Mode | What it is | Status in this build |
| --- | --- | --- |
| **MOCK** | A simulated broker and synthetic market data. Default. | Works fully offline |
| **PAPER** | Interactive Brokers paper account through IB Gateway | Needs your own IBKR account and configuration — externally unverified until then |
| **LIVE** | Real money | **Disabled and not authorized** |

Records are separated by mode: Mock orders never mix with Paper or Live ones, and Mock can never be pointed at a real endpoint.

## Live gate

Live would require all of: `LIVE_TRADING_ENABLED=true`, an authenticator app (TOTP), a fresh password confirmation, a checklist acknowledgement and a completed Paper verification. None of this is enabled in this build.

## Output labels

- **Simulated** — template or fixture text from the no-model baseline.
- **Computed** — produced by deterministic code (retrieval, calculations, checks).
- **Model-generated** — written by the local language model; verify it against the cited sources.
