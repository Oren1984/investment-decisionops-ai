---
title: Knowledge library, citations and deletion
category: Library
summary: Uploads, retrieval, evidence checks and the two deletion choices.
routes: /library
---
## Uploads

Allowed: text-based **PDF**, **Markdown**, **plain text** and **CSV**; up to 20 MB and 500 pages per file, 2 GB in total. Files are checked by extension *and* content, stored under random names outside the web root, and parsed in a separate process with a time and memory limit. Scanned PDFs are rejected (no OCR).

## Answers

- Without a model, answers are **extractive**: ranked passages quoted verbatim with their location.
- With the local model, a generated answer cites passages, and quoted evidence is shown separately from interpretation.
- If nothing relevant is found the answer is **“Not found in your library.”**

Retrieval is keyword search (Postgres full-text) by default; optional local embeddings add semantic search (`EMBEDDINGS_ENABLED=true`, one-time download).

## Evidence checks are heuristics

Citation presence, citation validity and quote fidelity are exact checks. The **lexical support** check only looks for key terms and numbers in the cited passage; a flag reads *“Possibly unsupported – check the source”*. Passing means “no obvious mismatch found”, **not** “supported”.

## Deleting a document

| | Remove from Library | Fully erase content |
| --- | --- | --- |
| File, passages, index | Deleted | Deleted |
| Quotes frozen in decisions | Kept, marked “Source removed” | **Erased**; decisions show *Evidence incomplete* |
| Agent outputs, answers, notes quoting it | Live caches deleted | Erased or redacted |
| Stored exports containing it | Kept | Deleted |
| Audit | Normal event | Minimal record without title or content |

Both are irreversible. Full erasure needs the word ERASE and your password. Downloads already made and material collaborators already saw cannot be recalled. Backups keep the document until they rotate out (30 days by default); an **erasure ledger** is re-applied automatically after any restore.
