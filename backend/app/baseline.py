"""Fixed-size baseline chunker, used only to evaluate code-aware chunking.

Splits a file into overlapping windows of N lines regardless of where functions
begin or end. It produces the same Chunk objects (1-indexed inclusive line
ranges) as the tree-sitter chunker, so both go through the identical
ingest -> embed -> retrieve pipeline and the chunking strategy is the only
variable. A baseline repo is stored under "<name>@fixed".
"""
from __future__ import annotations

from .chunker import Chunk

FIXED_SUFFIX = "@fixed"
DEFAULT_WINDOW = 40
DEFAULT_OVERLAP = 10


def chunk_fixed(source: str, path: str, window: int = DEFAULT_WINDOW,
                overlap: int = DEFAULT_OVERLAP) -> list[Chunk]:
    if window < 1 or not 0 <= overlap < window:
        raise ValueError("need window >= 1 and 0 <= overlap < window")
    lines = [ln.rstrip("\r") for ln in source.split("\n")]
    while lines and not lines[-1].strip():
        lines.pop()                      # trailing blank lines are not content
    n = len(lines)
    step = window - overlap
    chunks: list[Chunk] = []
    start = 1
    while start <= n:
        end = min(start + window - 1, n)
        body = lines[start - 1:end]
        if any(ln.strip() for ln in body):   # skip all-blank windows
            chunks.append(Chunk(path, start, end, "window", None, None, "\n".join(body)))
        if end == n:
            break                        # last window reached the end of the file
        start += step
    return chunks
