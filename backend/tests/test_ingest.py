from pathlib import Path

import pytest

from app.docs import chunk_markdown, chunk_plain
from app.ingest import iter_source_files

MD = """Intro text before any heading.

# Title

Some description.

## Install

```bash
# this is a comment, not a heading
pip install thing
```

## Empty section

## Usage

Run it.
"""


def test_markdown_sections_and_fences():
    chunks = chunk_markdown(MD, "README.md")
    titles = [c.symbol for c in chunks]
    assert titles == ["README.md", "Title", "Install", "Usage"]  # preamble + 3; empty dropped
    install = next(c for c in chunks if c.symbol == "Install")
    assert "pip install thing" in install.content
    assert "this is a comment" in install.content  # fence not split
    lines = MD.split("\n")
    for c in chunks:
        assert c.content == "\n".join(lines[c.start_line - 1:c.end_line])
        assert c.kind == "doc"


def test_plain_chunk_whole_file():
    chunks = chunk_plain("a = 1\nb = 2\n\n\n", "cfg/app.toml", "config")
    assert len(chunks) == 1
    assert (chunks[0].start_line, chunks[0].end_line) == (1, 2)
    assert chunks[0].symbol == "app.toml"


def test_file_filtering(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("def f():\n    return 1\n")
    (tmp_path / "README.md").write_text("# Hi\n\ntext\n")
    (tmp_path / "pyproject.toml").write_text("[tool]\nx = 1\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "skip.py").write_text("x = 1\n")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "skip2.py").write_text("x = 1\n")
    (tmp_path / "bin.py").write_bytes(b"x = 1\x00\x00")
    (tmp_path / "package-lock.json").write_text("{}")
    (tmp_path / "huge.py").write_text("x = 1\n" * 100_000)
    (tmp_path / "image.png").write_bytes(b"\x89PNG")

    found = {rel for rel, _, _ in iter_source_files(tmp_path)}
    assert found == {"pkg/a.py", "README.md", "pyproject.toml"}


def _db_available() -> bool:
    try:
        from app.db import get_conn
        get_conn().close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_ingest_roundtrip(tmp_path: Path):
    from app.db import get_conn
    from app.ingest import ingest

    (tmp_path / "svc.py").write_text(
        "def helper():\n    return 1\n\n\n"
        "def handler():\n    return helper()\n\n\n"
        "class A:\n    def m(self):\n        return helper()\n"
    )
    (tmp_path / "README.md").write_text("# Demo\n\nhello\n")
    name = "pytest-demo-repo"
    summary = ingest(str(tmp_path), name=name)
    try:
        assert summary["files"] == 2
        assert summary["symbols"] == 4  # helper, handler, A, m
        assert summary["by_kind"]["doc"] == 1
        with get_conn() as conn:
            callers = conn.execute(
                "SELECT c.symbol FROM refs f JOIN chunks c ON c.id=f.caller_chunk_id "
                "JOIN repos r ON r.id=f.repo_id WHERE r.name=%s AND f.callee_name='helper' "
                "ORDER BY c.symbol", (name,)).fetchall()
            assert [r[0] for r in callers] == ["handler", "m"]
            row = conn.execute(
                "SELECT count(*) FROM chunks c JOIN repos r ON r.id=c.repo_id "
                "WHERE r.name=%s AND c.tsv @@ plainto_tsquery('simple','helper')", (name,)
            ).fetchone()
            assert row[0] >= 2  # full-text column is populated
        ingest(str(tmp_path), name=name)  # re-index replaces, not duplicates
        with get_conn() as conn:
            n = conn.execute("SELECT count(*) FROM repos WHERE name=%s", (name,)).fetchone()[0]
            assert n == 1
    finally:
        with get_conn() as conn:
            conn.execute("DELETE FROM repos WHERE name=%s", (name,))
