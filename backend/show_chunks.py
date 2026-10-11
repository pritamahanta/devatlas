"""Step 2 checkpoint: python show_chunks.py <file.py | directory>"""
import sys
from pathlib import Path

from app.chunker import chunk_python

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist"}


def py_files(target: Path):
    if target.is_file():
        yield target
        return
    for p in sorted(target.rglob("*.py")):
        if not (set(p.parts) & SKIP_DIRS):
            yield p


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python show_chunks.py <file.py | directory>")
    root = Path(sys.argv[1])
    total = 0
    for f in py_files(root):
        rel = str(f.relative_to(root)) if root.is_dir() else f.name
        try:
            chunks = chunk_python(f.read_text(encoding="utf-8"), rel)
        except UnicodeDecodeError:
            continue
        for c in chunks:
            qual = f"{c.parent}.{c.symbol}" if c.parent else (c.symbol or "-")
            print(f"{c.kind:<9} {rel}:{c.start_line}-{c.end_line:<5} {qual}  calls={len(c.calls)}")
        total += len(chunks)
    print(f"\n{total} chunks")


if __name__ == "__main__":
    main()
