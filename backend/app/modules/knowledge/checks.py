"""Evidence checks for answers. These are HEURISTICS: they do not prove that a source supports a claim.

1. Citation presence   — every statement carries at least one citation.
2. Citation validity   — each cited chunk was retrieved for this question, is accessible, and its location exists.
3. Quote fidelity      — text presented as a quotation matches the chunk text exactly (whitespace-normalized).
4. Lexical support     — key terms and numbers of a statement appear in its cited chunks; otherwise the statement is
                         flagged "Possibly unsupported – check the source". Passing means "no obvious mismatch found".
5. Abstention          — when retrieval is weak the system answers "Not found in your library".
"""

import re

from app.modules.knowledge.text import key_terms, normalize_ws, numbers

DISCLAIMER = ("These checks are heuristics. Passing them means no obvious mismatch was found — not that the source "
              "proves the statement. Read the cited passage before relying on it.")

QUOTED = re.compile(r"[\"“]([^\"”]{12,})[\"”]")
SUPPORT_MIN_TERM_SHARE = 0.5


def lexical_support(statement: str, cited_texts: list[str]) -> tuple[bool, str | None]:
    source = " ".join(cited_texts)
    source_numbers = numbers(source)
    missing_numbers = [n for n in numbers(statement) if n not in source_numbers]
    if missing_numbers:
        return False, f"Number(s) not found in the cited source: {', '.join(sorted(missing_numbers)[:4])}"
    terms = key_terms(statement)
    if not terms:
        return True, None
    source_terms = key_terms(source)
    share = len(terms & source_terms) / len(terms)
    if share < SUPPORT_MIN_TERM_SHARE:
        return False, f"Only {round(share * 100)}% of key terms appear in the cited source"
    return True, None


def run_checks(statements: list[dict], retrieved: dict[str, dict], accessible_chunk_ids: set[str],
               abstained: bool) -> tuple[list[dict], list[dict]]:
    """Annotate statements with flags and return (statements, check_results)."""
    presence_fail = validity_fail = fidelity_fail = support_flags = 0
    for st in statements:
        st.setdefault("flags", [])
        cites = st.get("citations") or []
        if not cites:
            presence_fail += 1
            st["flags"].append("No citation")
            continue
        texts = []
        for cid in cites:
            chunk = retrieved.get(cid)
            if chunk is None or cid not in accessible_chunk_ids or not chunk.get("location"):
                validity_fail += 1
                st["flags"].append("Invalid citation")
            else:
                texts.append(chunk["text"])
        if not texts:
            continue
        joined = normalize_ws(" ".join(texts))
        if st.get("kind") == "quote" and normalize_ws(st["text"]) not in joined:
            fidelity_fail += 1
            st["flags"].append("Quote does not match the source")
        for q in QUOTED.findall(st["text"]):
            if normalize_ws(q) not in joined:
                fidelity_fail += 1
                st["flags"].append("Quoted text does not match the source")
        ok, reason = lexical_support(st["text"], texts)
        if not ok:
            support_flags += 1
            st["flags"].append(f"Possibly unsupported – check the source ({reason})")

    results = [
        {"key": "citation_presence", "name": "Every statement has a citation", "passed": presence_fail == 0,
         "detail": f"{presence_fail} statement(s) without citation" if presence_fail else "All statements cited",
         "heuristic": False},
        {"key": "citation_validity", "name": "Citations point to retrieved, accessible passages",
         "passed": validity_fail == 0,
         "detail": f"{validity_fail} invalid citation(s)" if validity_fail else "All citations valid", "heuristic": False},
        {"key": "quote_fidelity", "name": "Quotations match the source exactly", "passed": fidelity_fail == 0,
         "detail": f"{fidelity_fail} mismatch(es)" if fidelity_fail else "All quotations match", "heuristic": False},
        {"key": "lexical_support", "name": "Key terms and numbers appear in the cited source",
         "passed": support_flags == 0,
         "detail": f"{support_flags} statement(s) flagged 'Possibly unsupported'" if support_flags
         else "No obvious mismatch found", "heuristic": True},
        {"key": "abstention", "name": "Answers only when the library has relevant passages", "passed": True,
         "detail": "Abstained: not found in your library" if abstained else "Relevant passages found",
         "heuristic": True},
    ]
    return statements, results
