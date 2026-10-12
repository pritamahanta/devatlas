"""Chunkers for non-code files: Markdown docs and config/text files."""
from __future__ import annotations

import re

from .chunker import MAX_CHUNK_LINES, Chunk

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def _windows(lines: list[str], path: str, s: int, e: int, kind: str,
             symbol: str | None) -> list[Chunk]:
    out = []
    for i, ws in enumerate(range(s, e + 1, MAX_CHUNK_LINES)):
        we = min(ws + MAX_CHUNK_LINES - 1, e)
        out.append(Chunk(path, ws, we, kind, symbol, None,
                         "\n".join(lines[ws - 1:we]), [], part=i))
    return out


def chunk_markdown(text: str, path: str) -> list[Chunk]:
    """One chunk per heading section; '#' inside code fences is ignored."""
    lines = [ln.rstrip("\r") for ln in text.split("\n")]
    starts: list[tuple[int, str]] = []  # (1-indexed line, title)
    in_fence = False
    for i, ln in enumerate(lines, start=1):
        if _FENCE.match(ln):
            in_fence = not in_fence
        elif not in_fence:
            m = _HEADING.match(ln)
            if m:
                starts.append((i, m.group(2)))
    if not starts or starts[0][0] > 1:
        starts.insert(0, (1, path.rsplit("/", 1)[-1]))  # preamble section

    chunks: list[Chunk] = []
    for idx, (s, title) in enumerate(starts):
        e = (starts[idx + 1][0] - 1) if idx + 1 < len(starts) else len(lines)
        while e > s and not lines[e - 1].strip():
            e -= 1
        has_heading = bool(_HEADING.match(lines[s - 1]))
        body = [ln for ln in (lines[s:e] if has_heading else lines[s - 1:e]) if ln.strip()]
        if body:  # drop heading-only sections
            chunks += _windows(lines, path, s, e, "doc", title)
    return chunks


def chunk_plain(text: str, path: str, kind: str) -> list[Chunk]:
    """Whole file (split into windows if long): config files, .rst, .txt."""
    lines = [ln.rstrip("\r") for ln in text.split("\n")]
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return []
    return _windows(lines, path, 1, len(lines), kind, path.rsplit("/", 1)[-1])
