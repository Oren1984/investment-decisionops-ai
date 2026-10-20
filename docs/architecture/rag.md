# Knowledge library and retrieval (RAG)

## Pipeline

1. **Upload** (owner only): PDF (text-based), Markdown, plain text and CSV, checked by extension and magic bytes;
   size and quota caps; random storage IDs in a non-served directory (`/data/uploads` in the `appdata` volume).
2. **Chunking:** ~800-token windows with ~100-token overlap per page/section; each chunk keeps page and section
   for citations.
3. **Index:** PostgreSQL full-text search over chunk text plus the document title (always). Optional vectors:
   fastembed `BAAI/bge-small-en-v1.5` (384-dim, CPU) in pgvector when `EMBEDDINGS_ENABLED=true`.
4. **Retrieval:** FTS ranking, merged with vector similarity when enabled.
5. **Answer:** *extractive* by default: verbatim sentences with citations `<title> (§ <section>)`. No model is
   needed. If the best hit's term coverage is below 0.4 and its vector similarity (when enabled) is below 0.78,
   the system **abstains** ("Not found in your library") instead of guessing.

## Evidence checks: what they are and are not

`backend/app/modules/knowledge/checks.py` runs five heuristics on answers and on the citations used in evidence
packages: citation presence; citation validity (the chunk was retrieved, is accessible, its location exists);
quote fidelity (quoted text matches the chunk exactly, whitespace-normalized); lexical support (key terms and
numbers of a statement appear in its cited chunks, otherwise "Possibly unsupported – check the source"); and
abstention. They are labelled **Heuristic** in the UI. Passing them means no obvious mismatch was found, **not**
that the source proves the statement or is reliable.

## Evaluation (from the test suite, 20 Oct 2026)

Fixture set: synthetic documents with 33 answerable and 8 unanswerable questions
(`backend/tests/fixtures/rag_eval`), FTS only (embeddings disabled):

| Metric | Result |
| --- | --- |
| Recall@5 (answerable) | **0.97** (32/33) |
| MRR | **0.97** |
| Answered when answerable | 1.00 |
| Abstained when unanswerable | 1.00 |
| Retrieval misses | "When should the portfolio be rebalanced?" |

Unsupported-claim heuristic: flagged **10/10** unsupported claims, **0/4** false positives on supported ones.

These numbers describe a small synthetic set and catch regressions; they are not a general quality claim.

## Deletion: two explicit choices (owner decision D7)

| | Remove from library | Erase completely |
| --- | --- | --- |
| Document, chunks, index, file | Removed | Removed |
| Frozen quotations in past decisions | **Kept**, marked "source removed" | **Redacted**; evidence marked incomplete with a visible redaction event |
| Derived copies (answers, notes quoting it, agent outputs, exports) | Kept | Redacted or deleted |
| Audit | Normal event | Minimal non-content record |
| Confirmation | Dialog listing concrete effects | Step-up + typing `ERASE` |
| Erasure ledger | Entry written | Entry written |

Both modes write an erasure-ledger entry so a restore from an older backup re-applies the deletion
([operations.md](../guides/operations.md#erasure-ledger)). Hash verification of a redacted evidence package still passes for
every remaining item and reports the redacted ones separately.
