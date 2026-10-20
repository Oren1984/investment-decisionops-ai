"""Sandboxed document parser. Runs as a separate process with a timeout and (on Linux) a memory limit.

Usage: python -m app.modules.knowledge.parse_worker <path> <file_type> <max_pages>
Writes JSON to stdout: {"pages": [{"page": int|None, "section": str|None, "text": str}]} or {"error": "..."}.
Scripts, attachments and embedded files in PDFs are never executed or extracted.
"""

import csv
import io
import json
import re
import sys

MEMORY_LIMIT_BYTES = 768 * 1024 * 1024


def _limit_memory() -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
    except (ImportError, ValueError, OSError):
        pass


def parse_pdf(data: bytes, max_pages: int) -> list[dict]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ValueError("Encrypted PDFs are not supported. Remove the password and upload again.")
    if len(reader.pages) > max_pages:
        raise ValueError(f"The PDF has {len(reader.pages)} pages; the limit is {max_pages}.")
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append({"page": i, "section": None, "text": text})
    if not pages:
        raise ValueError("No text found. This looks like a scanned PDF – OCR is not supported.")
    return pages


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def parse_markdown(text: str) -> list[dict]:
    sections: list[dict] = []
    current = {"page": None, "section": None, "text": ""}
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            if current["text"].strip():
                sections.append(current)
            current = {"page": None, "section": m.group(2)[:200], "text": ""}
        else:
            current["text"] += line + "\n"
    if current["text"].strip():
        sections.append(current)
    return sections


def parse_csv(text: str) -> list[dict]:
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return []
    header, body = rows[0], rows[1:]
    out = []
    for start in range(0, len(body), 40):
        block = body[start:start + 40]
        lines = ["; ".join(f"{h}: {v}" for h, v in zip(header, row, strict=False)) for row in block]
        out.append({"page": None, "section": f"Rows {start + 1}–{start + len(block)}", "text": "\n".join(lines)})
    return out


def parse(path: str, file_type: str, max_pages: int) -> list[dict]:
    with open(path, "rb") as fh:
        data = fh.read()
    if file_type == "pdf":
        return parse_pdf(data, max_pages)
    text = data.decode("utf-8")
    if file_type == "md":
        return parse_markdown(text)
    if file_type == "csv":
        return parse_csv(text)
    return [{"page": None, "section": None, "text": text}]


def main() -> None:
    _limit_memory()
    path, file_type, max_pages = sys.argv[1], sys.argv[2], int(sys.argv[3])
    try:
        result = {"pages": parse(path, file_type, max_pages)}
    except Exception as exc:  # noqa: BLE001 - report a readable error to the parent
        result = {"error": str(exc)[:500] or exc.__class__.__name__}
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
