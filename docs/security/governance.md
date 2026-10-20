# Governance

## Owner control

Only the owner can approve or submit orders, press or release Stop, share material, invite or revoke
collaborators, change limits and trading mode, upload or delete documents, erase data and change settings. Live
trading cannot be activated in this build. Every consequential action is written to the audit log (`audit_event`),
which records the actor, the object and non-content details.

## Permitted actions

| Capability | Owner | Collaborator | Demo visitor | Agents |
| --- | --- | --- | --- | --- |
| Portfolio, orders, broker data | ✔ | ✘ | Synthetic, read-only | Read positions/exposure via MCP |
| Run workflows | ✔ | ✘ | ✘ (views recorded runs) | — |
| Approve / submit orders, Stop | ✔ | ✘ | ✘ | ✘ (no tool exists) |
| Upload / delete documents | ✔ | ✘ | ✘ | ✘ |
| View shared objects | ✔ | Granted only | Synthetic only | Run scope only |
| Comment, action items | ✔ | ✔ with a comment grant | ✘ | ✘ |
| Settings, integrations, invites, audit, ops | ✔ | Own profile and MFA | ✘ | ✘ |

Enforced server-side: each route declares one permission (route-inventory test), object checks run in services,
and agents act only through capability-scoped, read/compute MCP tools ([agents-and-mcp.md](../architecture/agents-and-mcp.md)).

## AI controls

- Outputs are labelled **Simulated**, **Computed** or **Model-generated**; numbers are always Computed.
- No confidence percentages are shown; the checklist reports process completeness, not idea quality.
- Agent proposals are inert until the owner acts through normal screens.
- Prompts are versioned files (`backend/prompts/*.v1.toml`); each step records the prompt version and the model
  name and digest. Changing the model or a prompt should be recorded in [`DECISIONS.md`](../project/DECISIONS.md) and followed by a re-run of
  the RAG evaluation and J4.

## Evidence integrity

Evidence packages are frozen with per-item SHA-256 hashes when a decision is recorded. Replays read the frozen
snapshot. Corrections create new decision versions; they never edit the frozen package. Erasure redacts items
visibly and verification reports redacted items separately. `python -m app.cli verify-evidence` recomputes all
hashes (run automatically by the restore scripts).

## Incident runbook

1. **Stop** (header button): blocks new submissions and agent runs immediately.
2. **Assess:** Orders (uncertain, open), Ops page, alerts, audit log.
3. **Reconcile:** run reconciliation; the broker is the source of truth for fills.
4. **Cancel open orders** if needed (a separate, tracked step: Stop does not cancel).
5. **Document** what happened (decision note or review).
6. **Lessons:** record them in the decision review; release Stop when safe.

See also [regulatory-notes.md](regulatory-notes.md) and Help → *Governance*.
