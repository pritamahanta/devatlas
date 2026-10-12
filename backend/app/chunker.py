"""Code-aware chunker for Python source using tree-sitter.

One chunk per function / method; a class becomes a header chunk (signature,
docstring, class-level statements) plus one chunk per method. Leftover
module-level code (imports, app setup, routes registered at module level)
becomes 'module' chunks. Line numbers are 1-indexed and inclusive so they
can be used directly as citations.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

PY_LANGUAGE = Language(tspython.language())
_parser = Parser(PY_LANGUAGE)

MAX_CHUNK_LINES = 150  # oversized functions are split into windows of this size
MIN_MODULE_LINES = 2   # skip module gaps with fewer non-blank lines


def build_embed_text(path: str, kind: str, parent: str | None,
                     symbol: str | None, content: str) -> str:
    """Context header + raw content. Shared by ingestion and the embed step."""
    qual = f"{parent}.{symbol}" if parent and symbol else (symbol or "")
    header = f"# file: {path}\n# {kind}: {qual}".rstrip()
    return f"{header}\n{content}"


@dataclass
class Chunk:
    path: str
    start_line: int
    end_line: int
    kind: str                 # function | method | class | module
    symbol: str | None        # e.g. create_user
    parent: str | None        # enclosing class qualname, e.g. Outer.Inner
    content: str              # raw source, so line ranges match the file
    calls: list[str] = field(default_factory=list)  # callee names (for refs)
    part: int = 0             # >0 for continuation windows of an oversized chunk

    def embed_text(self) -> str:
        """Text sent to the embedding model: raw code plus a context header."""
        return build_embed_text(self.path, self.kind, self.parent, self.symbol, self.content)


def _calls_in(node: Node) -> list[str]:
    """Unique callee names inside a node (foo() -> foo, a.b.foo() -> foo)."""
    names: list[str] = []
    seen: set[str] = set()
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "call":
            fn = n.child_by_field_name("function")
            name = None
            if fn is not None:
                if fn.type == "identifier":
                    name = fn.text.decode()
                elif fn.type == "attribute":
                    attr = fn.child_by_field_name("attribute")
                    name = attr.text.decode() if attr is not None else None
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        stack.extend(n.children)
    return names


def _rows(node: Node) -> tuple[int, int]:
    """1-indexed inclusive (start, end) lines of a node."""
    end_row = node.end_point[0]
    if node.end_point[1] == 0 and end_row > node.start_point[0]:
        end_row -= 1  # node ended at the very start of the next line
    return node.start_point[0] + 1, end_row + 1


def _unwrap(node: Node) -> Node | None:
    """decorated_definition -> inner function/class; else the node if it is one."""
    if node.type == "decorated_definition":
        return node.child_by_field_name("definition")
    if node.type in ("function_definition", "class_definition"):
        return node
    return None


def _make(lines: list[str], path: str, s: int, e: int, kind: str,
          symbol: str | None, parent: str | None, calls: list[str]) -> list[Chunk]:
    """Build a chunk, splitting into windows if it exceeds MAX_CHUNK_LINES."""
    out: list[Chunk] = []
    for i, ws in enumerate(range(s, e + 1, MAX_CHUNK_LINES)):
        we = min(ws + MAX_CHUNK_LINES - 1, e)
        out.append(Chunk(path, ws, we, kind, symbol, parent,
                         "\n".join(lines[ws - 1:we]), calls, part=i))
    return out


def _walk_block(block: Node, lines: list[str], path: str,
                parent: str | None, covered: list[tuple[int, int]]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for child in block.children:
        inner = _unwrap(child)
        if inner is None:
            continue
        s, e = _rows(child)  # child includes decorators
        name_node = inner.child_by_field_name("name")
        name = name_node.text.decode() if name_node else None

        if inner.type == "function_definition":
            kind = "method" if parent else "function"
            chunks += _make(lines, path, s, e, kind, name, parent, _calls_in(inner))
            covered.append((s, e))
        else:  # class_definition
            body = inner.child_by_field_name("body")
            qual = f"{parent}.{name}" if parent else name
            nested = _walk_block(body, lines, path, qual, covered) if body else []
            member_starts = [c.start_line for c in nested]
            header_end = (min(member_starts) - 1) if member_starts else e
            while header_end > s and not lines[header_end - 1].strip():
                header_end -= 1  # trim trailing blank lines
            chunks += _make(lines, path, s, header_end, "class", name, parent, [])
            covered.append((s, header_end))
            chunks += nested
    return chunks


def chunk_python(source: str, path: str) -> list[Chunk]:
    lines = [ln.rstrip("\r") for ln in source.split("\n")]
    tree = _parser.parse(source.encode("utf-8"))
    covered: list[tuple[int, int]] = []
    chunks = _walk_block(tree.root_node, lines, path, None, covered)

    # leftover module-level code (imports, constants, app = FastAPI(), ...)
    covered.sort()
    gaps, cursor = [], 1
    for s, e in covered:
        if s > cursor:
            gaps.append((cursor, s - 1))
        cursor = max(cursor, e + 1)
    if cursor <= len(lines):
        gaps.append((cursor, len(lines)))
    for gs, ge in gaps:
        while gs <= ge and not lines[gs - 1].strip():
            gs += 1
        while ge >= gs and not lines[ge - 1].strip():
            ge -= 1
        if sum(1 for ln in lines[gs - 1:ge] if ln.strip()) >= MIN_MODULE_LINES:
            chunks += _make(lines, path, gs, ge, "module", None, None, [])

    chunks.sort(key=lambda c: (c.start_line, c.end_line))
    return chunks
