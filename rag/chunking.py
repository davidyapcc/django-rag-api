"""Split text into overlapping chunks on paragraph and sentence boundaries."""

import re

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def chunk_text(text: str, max_chars: int = 800, overlap_chars: int = 150) -> list[str]:
    if max_chars <= overlap_chars:
        raise ValueError("max_chars must be greater than overlap_chars")
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        return []

    units: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = " ".join(para.split())
        if not para:
            continue
        if len(para) <= max_chars:
            units.append(para)
            continue
        for sentence in _SENTENCE_SPLIT.split(para):
            # Hard-wrap sentences that are longer than a chunk on their own.
            units.extend(sentence[i : i + max_chars] for i in range(0, len(sentence), max_chars))

    chunks: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}\n\n{unit}" if current else unit
        if len(candidate) <= max_chars:
            current = candidate
            continue
        chunks.append(current)
        tail = current[-overlap_chars:]
        # Start the overlap on a word boundary.
        tail = tail[tail.find(" ") + 1 :] if " " in tail else tail
        current = f"{tail}\n\n{unit}" if len(tail) + len(unit) + 2 <= max_chars else unit
    if current:
        chunks.append(current)
    return chunks
