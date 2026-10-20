---
title: Agents, the manager flow and MCP tools
category: Decisions
summary: How the agent team works in both modes, and what agents can never do.
routes: /decisions
---
One workflow, two execution modes:

- **Deterministic (always available)** — a CrewAI **Flow** orchestrates scope → research → analysis → scenarios → critic. Research retrieves real passages from your library (Computed) and writes a *Simulated* summary. Analysis, scenarios and checks are *Computed*.
- **Model-enabled** — the same Flow, plus real CrewAI agents per role and an optional advisory manager on your local model. They interpret and select; **numbers stay Computed**. Invalid model output gets one retry, then a computed fallback with a visible note.

## Tools and permissions

Agents use an internal MCP tool server (no network listener). Tools are **read or compute only**: search the library, read quotes, calendars, positions and exposure, run scenarios and checks. There are **no tools** for orders, cancels, sharing, invites, settings, approvals or deletion. Every call is authorized server-side with a short-lived run capability token and a call budget.

## Suggestions are inert

Agents can propose follow-up research, an order intent, a share or a reminder. These appear under **Suggestions (not executed)**. Nothing happens unless you act through the normal screens.

## Cancel and resume

Cancel stops the run at the next check (model calls are abandoned). Resume continues from the last completed step; completed steps are never repeated.
