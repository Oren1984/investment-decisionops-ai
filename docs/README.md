# Documentation

Start with the [project README](../README.md) for what the app does and how to run it. This folder holds the
details. Statuses use the four labels from [`PROJECT_PLAN.md`](project/PROJECT_PLAN.md) §5, and documents describe what is actually built and
verified.

## Run and operate

| Document | What you'll find |
| --- | --- |
| [Setup](guides/setup.md) | Requirements, first start with Docker on port 8087, owner account, demo access, configuration, offline operation, development |
| [Operations](guides/operations.md) | Start/stop/update, backup and restore (sh and PowerShell), erasure ledger, alerts, health, CLI, incident runbook |
| [Deployment](guides/deployment.md) | Cloud recommendation (AWS Lightsail) and the Terraform module. Nothing is deployed |
| [Known limitations](known-limitations.md) | Integration status and honest product limits |

## Use the app

The in-app **Help Center** (`/help`) is the user guide. Its sources live in [`help/`](../help/), for example:

- [Meetings: Zoom, Google Meet, Microsoft Teams and other links](../help/zoom-meetings.md)
- [Getting started](../help/getting-started.md) · [First run and recovery](../help/first-run-and-recovery.md)
- [Approvals and Stop](../help/approvals-and-stop.md) · [Knowledge library](../help/knowledge-library.md)

## How it's built

| Document | What you'll find |
| --- | --- |
| [Architecture overview](architecture/overview.md) | Components, Compose services, modules, key flows (with diagram) |
| [Agents and MCP](architecture/agents-and-mcp.md) | Deterministic and model-enabled workflow, the read/compute MCP tool boundary |
| [Knowledge library and retrieval](architecture/rag.md) | Ingestion, keyword retrieval, citations, evidence checks, deletion modes |
| [Broker integration](architecture/broker-integration.md) | Mock broker, IBKR Paper adapter, order flow and controls |

## Security and governance

| Document | What you'll find |
| --- | --- |
| [Threat model](security/threat-model.md) | Threats, mitigations and the tests that cover them |
| [Governance](security/governance.md) | Who may do what (owner, collaborator, demo, agents), AI controls, evidence integrity |
| [Dependency findings](security/dependency-findings.md) | Scan results and reviewed exceptions |
| [Regulatory notes](security/regulatory-notes.md) | Not legal advice; where qualified review is needed |

## Testing and evidence

- [Testing](testing/README.md): test layers, how to run E2E on the isolated stack, journey list.
- [Evidence, 20 Oct 2026](testing/evidence-2026-10-20.md): exact commands and results.

## Screenshots

[`screenshots/`](screenshots/) are taken from the read-only demo (synthetic data) by
`SCREENSHOTS=1 npx playwright test z-screenshots`: overview (desktop and mobile), markets, portfolio, decisions,
decision evidence, orders, library, collaboration (meetings) and help.

## Project records

| Document | What you'll find |
| --- | --- |
| [Project plan](project/PROJECT_PLAN.md) | The approved, authoritative plan: scope, status labels (§5), journeys, testing |
| [Tasks](project/TASKS.md) | Delivery status per area, with evidence and next actions |
| [Decisions](project/DECISIONS.md) | Owner decisions and implementation deviations, with reasons |
| [Agent instructions](../AGENTS.md) | Rules for coding agents working in this repository |
