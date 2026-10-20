"""Chunking and light lexical helpers shared by retrieval and the evidence checks."""

import re

CHUNK_TOKENS = 800
OVERLAP_TOKENS = 100
_WORD = re.compile(r"[A-Za-z][A-Za-z\-']+|\d[\d,.]*%?")
_NUMBER = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?%?")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")

STOPWORDS = set("""a an and are as at be been but by can could did do does for from had has have how i if in into is it
its may might more most must no not of on or our over should so such than that the their them then there these they this
those to under up was we were what when where which while who why will with would you your about above after again all
also any because before being below between both down during each few further here just only other out own same some
very""".split())


def tokens_estimate(text: str) -> int:
    return max(1, int(len(text.split()) * 1.33))


def chunk_pages(pages: list[dict]) -> list[dict]:
    """~800-token chunks with ~100-token overlap, keeping page/section for citations."""
    chunks: list[dict] = []
    max_words = int(CHUNK_TOKENS / 1.33)
    overlap_words = int(OVERLAP_TOKENS / 1.33)
    for page in pages:
        words = page["text"].split()
        if not words:
            continue
        start = 0
        while start < len(words):
            end = min(len(words), start + max_words)
            text = " ".join(words[start:end])
            chunks.append({"text": text, "page": page.get("page"), "section": page.get("section"),
                           "token_count": tokens_estimate(text)})
            if end == len(words):
                break
            start = end - overlap_words
    return chunks


def stem(word: str) -> str:
    w = word.lower().strip("'")
    for suffix in ("ingly", "edly", "ing", "ies", "ied", "es", "ed", "ly", "s"):
        if len(w) > len(suffix) + 3 and w.endswith(suffix):
            return w[: -len(suffix)]
    return w


def key_terms(text: str) -> set[str]:
    return {stem(w) for w in _WORD.findall(text) if not w[0].isdigit() and len(w) >= 4 and w.lower() not in STOPWORDS}


def numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in _NUMBER.findall(text)}


def sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT.split(" ".join(text.split()))]
    return [p for p in parts if len(p) >= 20]


def normalize_ws(text: str) -> str:
    return " ".join(text.split())


INSTRUCTION_PATTERNS = re.compile(
    r"ignore (all |any )?(previous|prior|above) instructions|disregard (the )?(system|previous)|you are now|"
    r"system prompt|act as (an? )?(admin|administrator|developer)|submit (an? )?order|execute (the )?trade|"
    r"approve (the )?order|call the tool|<\s*/?\s*(system|instructions)\s*>",
    re.I,
)


def instruction_like(text: str) -> bool:
    """Flags text that looks like an attempt to instruct the agents (prompt injection). Heuristic."""
    return bool(INSTRUCTION_PATTERNS.search(text))
