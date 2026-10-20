---
title: Decisions, evidence and replay
category: Decisions
summary: From question to frozen evidence, decision versions and replay.
routes: /decisions
---
## The workflow

Draft → Scoped → Researching → Analyzing → Scenarios → Quality review → **Ready for decision** → Decided → (Execution linked) → Under review → Closed.

When the quality review completes, the system **freezes an evidence snapshot**: every source, data point, passage and agent output becomes an item with a salted hash, and the snapshot gets a hash over all items. A database trigger rejects any later change, except the controlled erasure described in [Knowledge library](/help/knowledge-library).

## Deciding

Record accept, reject or defer with a rationale. The decision is bound to the snapshot. To change your mind, record a **correction**: it creates a new version with an explanation; the original stays visible.

## Replay

Replay reads only the frozen snapshot of a version. Later market data can never change it. If evidence was erased, replay shows *Evidence incomplete* and the remaining items still verify.

## Blocked runs

If no instrument can be identified, or research finds no sources, the decision becomes **Blocked** with the reason. Edit the question and start a new run.
